use std::sync::OnceLock;

use regex::{Captures, Regex};

use crate::protocol::http::{Body, BodyContent};

/// Scrubbing patterns, with their regex form compiled on first use.
///
/// Regexes are only used for bodies that are not structured data; the
/// structured paths walk the parsed value instead, which is both exact and
/// cheaper than a regex sweep. Compiling them up front cost more than opening a
/// small cassette did, and a cassette of JSON bodies never reaches them at all.
#[derive(Clone, Debug)]
pub struct Scrubber {
    patterns: Vec<String>,
    lower_patterns: Vec<String>,
    json_re: OnceLock<Vec<Regex>>,
    form_re: OnceLock<Vec<Regex>>,
}

/// Longest pattern accepted without compiling it to check.
///
/// `regex::escape` turns a pattern into a literal, so the only way a template
/// fails to compile is a pattern long enough to blow the regex size limit -
/// which takes hundreds of kilobytes, two orders of magnitude past this. A
/// pattern beyond it is compiled up front instead, so an unusable one is still
/// rejected where it was passed in rather than at the first body that needs it.
const MAX_UNCHECKED_PATTERN: usize = 4 * 1024;

// Both templates are `(?i)` over an escaped key, so key matching mirrors
// `matches_key`: case-insensitive substring.
fn json_template(key: &str) -> String {
    format!(
        r#"(?i)("[^"]*{key}[^"]*"\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)"#
    )
}

fn form_template(key: &str) -> String {
    format!(r"(?i)([^&\s=]*{key}[^&\s=]*=)[^&\s]*")
}

fn compile(patterns: &[String], template: fn(&str) -> String) -> Result<Vec<Regex>, regex::Error> {
    patterns
        .iter()
        .map(|pattern| Regex::new(&template(&regex::escape(pattern))))
        .collect()
}

/// Compile from a lazy getter, where the patterns are known to be short enough
/// that [`compile`] cannot fail.
fn compile_checked(patterns: &[String], template: fn(&str) -> String) -> Vec<Regex> {
    compile(patterns, template).expect("patterns this short are literals that always compile")
}

impl Scrubber {
    pub fn new(patterns: &[String]) -> Result<Self, regex::Error> {
        let oversized = patterns.iter().any(|p| p.len() > MAX_UNCHECKED_PATTERN);
        Ok(Scrubber {
            lower_patterns: patterns.iter().map(|p| p.to_lowercase()).collect(),
            // Priming these leaves the lazy getters unreachable for the patterns
            // that could have failed, so their `expect` holds by construction.
            json_re: match oversized {
                true => OnceLock::from(compile(patterns, json_template)?),
                false => OnceLock::new(),
            },
            form_re: match oversized {
                true => OnceLock::from(compile(patterns, form_template)?),
                false => OnceLock::new(),
            },
            patterns: patterns.to_vec(),
        })
    }

    fn json_re(&self) -> &[Regex] {
        self.json_re
            .get_or_init(|| compile_checked(&self.patterns, json_template))
    }

    fn form_re(&self) -> &[Regex] {
        self.form_re
            .get_or_init(|| compile_checked(&self.patterns, form_template))
    }

    fn matches_key(&self, key: &str) -> bool {
        let key_lower = key.to_lowercase();
        self.lower_patterns.iter().any(|p| key_lower.contains(p))
    }

    /// Scrub sensitive patterns from a Body.
    pub fn scrub_body(&self, body: &Body, replacement: &str) -> Body {
        match &body.inner {
            BodyContent::Json(value) => Body::json(self.scrub_json_value(value, replacement)),
            BodyContent::Text(text) => Body::text(self.scrub_text(text, replacement)),
            BodyContent::Binary(_) | BodyContent::None => body.clone(),
        }
    }

    /// Scrub JSON values: replace values of keys that match sensitive patterns.
    pub fn scrub_json_value(
        &self,
        value: &serde_json::Value,
        replacement: &str,
    ) -> serde_json::Value {
        let mut scrubbed = value.clone();
        self.scrub_json_in_place(&mut scrubbed, replacement);
        scrubbed
    }

    /// Scrub a parsed tree in place, reporting whether anything was replaced.
    ///
    /// A caller that owns its tree walks it once instead of rebuilding it into a
    /// fresh map and deep-comparing the two, which is the difference between one
    /// allocation per object and three on a streaming body with a `data:` payload
    /// per chunk.
    fn scrub_json_in_place(&self, value: &mut serde_json::Value, replacement: &str) -> bool {
        match value {
            serde_json::Value::Object(map) => {
                let mut scrubbed = false;
                for (key, val) in map.iter_mut() {
                    if !self.matches_key(key) {
                        scrubbed |= self.scrub_json_in_place(val, replacement);
                    } else if val.as_str() != Some(replacement) {
                        // A value already holding the replacement is left alone, so a
                        // re-scrub reports no change and the body is not reformatted.
                        *val = serde_json::Value::String(replacement.to_string());
                        scrubbed = true;
                    }
                }
                scrubbed
            }
            serde_json::Value::Array(arr) => {
                let mut scrubbed = false;
                for val in arr.iter_mut() {
                    scrubbed |= self.scrub_json_in_place(val, replacement);
                }
                scrubbed
            }
            _ => false,
        }
    }

    /// Scrub a text body.
    ///
    /// Text that is itself structured gets parsed and scrubbed as a tree, so
    /// nested objects, arrays and non-string values are covered exactly as
    /// they would be in a `json` body. Regexes are the last resort, and only
    /// reach genuinely unstructured payloads.
    fn scrub_text(&self, text: &str, replacement: &str) -> String {
        if let Some(scrubbed) = self.scrub_json_text(text, replacement) {
            return scrubbed;
        }
        if let Some(scrubbed) = self.scrub_sse(text, replacement) {
            return scrubbed;
        }
        self.scrub_unstructured(text, replacement)
    }

    /// Scrub text that parses as a whole JSON document.
    ///
    /// Returns `None` when the text is not JSON. Returns the original text
    /// unchanged when nothing matched, so bodies without secrets are never
    /// reformatted.
    fn scrub_json_text(&self, text: &str, replacement: &str) -> Option<String> {
        let mut parsed: serde_json::Value = serde_json::from_str(text).ok()?;
        if !self.scrub_json_in_place(&mut parsed, replacement) {
            return Some(text.to_string());
        }
        serde_json::to_string(&parsed).ok()
    }

    /// Scrub `data:` payloads of a Server-Sent Events stream.
    ///
    /// SSE is the dominant response shape for streaming APIs, and each `data:`
    /// payload is usually a JSON document, so it gets the same tree treatment.
    fn scrub_sse(&self, text: &str, replacement: &str) -> Option<String> {
        if !text.lines().any(|line| line.starts_with("data:")) {
            return None;
        }
        let mut out = String::with_capacity(text.len());
        for line in text.split_inclusive('\n') {
            let (body, newline) = match line.strip_suffix('\n') {
                Some(rest) => (rest.strip_suffix('\r').unwrap_or(rest), true),
                None => (line, false),
            };
            match body.strip_prefix("data:") {
                Some(payload) => {
                    let trimmed = payload.trim_start();
                    let lead = &payload[..payload.len() - trimmed.len()];
                    let scrubbed = self
                        .scrub_json_text(trimmed, replacement)
                        .unwrap_or_else(|| self.scrub_unstructured(trimmed, replacement));
                    out.push_str("data:");
                    out.push_str(lead);
                    out.push_str(&scrubbed);
                }
                None => out.push_str(body),
            }
            if newline {
                out.push_str(if line.ends_with("\r\n") { "\r\n" } else { "\n" });
            }
        }
        Some(out)
    }

    /// Best-effort regex sweep for payloads with no parseable structure.
    fn scrub_unstructured(&self, text: &str, replacement: &str) -> String {
        let mut result = text.to_string();
        // A closure replacer is used throughout: `Regex::replace_all` expands
        // `$name` in a string replacement, so a replacement like `$0` would
        // re-emit the secret it is meant to hide.
        for re in self.json_re() {
            result = re
                .replace_all(&result, |c: &Captures<'_>| {
                    format!("{}\"{}\"", &c[1], replacement)
                })
                .into_owned();
        }
        for re in self.form_re() {
            result = re
                .replace_all(&result, |c: &Captures<'_>| {
                    format!("{}{}", &c[1], replacement)
                })
                .into_owned();
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scrubber(patterns: &[&str]) -> Scrubber {
        Scrubber::new(&patterns.iter().map(|p| p.to_string()).collect::<Vec<_>>()).unwrap()
    }

    fn scrub_text(text: &str, patterns: &[&str]) -> String {
        scrubber(patterns).scrub_text(text, "[FILTERED]")
    }

    #[test]
    fn test_scrub_json_body() {
        let value = serde_json::json!({
            "username": "alice",
            "password": "secret123",
            "nested": {"access_token": "tok_abc", "data": "keep"}
        });
        let scrubbed =
            scrubber(&["password", "access_token"]).scrub_json_value(&value, "[FILTERED]");

        assert_eq!(scrubbed["password"], "[FILTERED]");
        assert_eq!(scrubbed["nested"]["access_token"], "[FILTERED]");
        assert_eq!(scrubbed["username"], "alice");
        assert_eq!(scrubbed["nested"]["data"], "keep");
    }

    #[test]
    fn test_scrub_text_json_pattern() {
        let scrubbed = scrub_text(r#"{"password": "secret", "name": "alice"}"#, &["password"]);
        assert!(scrubbed.contains(r#""password":"[FILTERED]""#));
        assert!(scrubbed.contains(r#""name":"alice""#));
    }

    #[test]
    fn test_scrub_text_form_pattern() {
        let scrubbed = scrub_text(
            "grant_type=password&password=secret&username=alice",
            &["password"],
        );
        assert!(scrubbed.contains("password=[FILTERED]"));
        assert!(scrubbed.contains("username=alice"));
    }

    #[test]
    fn test_text_json_array_value_is_scrubbed() {
        let scrubbed = scrub_text(
            r#"{"access_token": ["sk-live-DEADBEEF"]}"#,
            &["access_token"],
        );
        assert!(!scrubbed.contains("sk-live-DEADBEEF"), "{scrubbed}");
    }

    #[test]
    fn test_text_json_object_value_is_scrubbed() {
        let scrubbed = scrub_text(r#"{"password": {"v": "sk-live-DEADBEEF"}}"#, &["password"]);
        assert!(!scrubbed.contains("sk-live-DEADBEEF"), "{scrubbed}");
    }

    #[test]
    fn test_text_json_numeric_value_is_scrubbed() {
        let scrubbed = scrub_text(r#"{"access_token": 1234567890}"#, &["access_token"]);
        assert!(!scrubbed.contains("1234567890"), "{scrubbed}");
    }

    #[test]
    fn test_text_json_escaped_quote_does_not_leak_tail() {
        let scrubbed = scrub_text(
            r#"{"password": "aaa\"SECRET-TAIL", "keep": "yes"}"#,
            &["password"],
        );
        assert!(!scrubbed.contains("SECRET-TAIL"), "{scrubbed}");
        assert!(scrubbed.contains("yes"));
    }

    #[test]
    fn test_unstructured_escaped_quote_does_not_leak_tail() {
        // Same shape, but embedded in a payload that is not valid JSON, so the
        // regex fallback has to handle the escape itself.
        let scrubbed = scrub_text(
            r#"prefix {"password": "aaa\"SECRET-TAIL"} trailing"#,
            &["password"],
        );
        assert!(!scrubbed.contains("SECRET-TAIL"), "{scrubbed}");
    }

    #[test]
    fn test_unstructured_non_string_value() {
        let scrubbed = scrub_text(
            r#"junk {"access_token": 1234567890} junk"#,
            &["access_token"],
        );
        assert!(!scrubbed.contains("1234567890"), "{scrubbed}");
    }

    #[test]
    fn test_sse_data_payload_is_scrubbed() {
        let text = "event: message\ndata: {\"password\": [\"hunter2-REAL\"]}\n\n";
        let scrubbed = scrub_text(text, &["password"]);
        assert!(!scrubbed.contains("hunter2-REAL"), "{scrubbed}");
        assert!(scrubbed.starts_with("event: message\n"));
        assert!(scrubbed.ends_with("\n\n"));
    }

    #[test]
    fn test_sse_preserves_crlf_and_done_sentinel() {
        let text = "data: {\"access_token\": \"tok\"}\r\ndata: [DONE]\r\n\r\n";
        let scrubbed = scrub_text(text, &["access_token"]);
        assert!(!scrubbed.contains("\"tok\""), "{scrubbed}");
        assert!(scrubbed.contains("data: [DONE]\r\n"), "{scrubbed}");
    }

    #[test]
    fn test_replacement_with_dollar_is_literal() {
        // `$0` in a string replacement would expand to the whole match and
        // re-emit the secret.
        let scrubber = scrubber(&["password"]);
        let scrubbed = scrubber.scrub_text("password=hunter2", "$0");
        assert_eq!(scrubbed, "password=$0");
        assert_eq!(
            scrubber.scrub_text("password=hunter2", "US$5.00"),
            "password=US$5.00"
        );
    }

    #[test]
    fn test_clean_json_text_is_not_reformatted() {
        let text = "{\n  \"name\": \"alice\"\n}";
        assert_eq!(scrub_text(text, &["password"]), text);
    }

    #[test]
    fn test_oversized_pattern_is_rejected_up_front() {
        let huge = "a".repeat(1024 * 1024);
        assert!(Scrubber::new(&[huge]).is_err());
    }

    /// The longest pattern accepted unchecked, driven through the lazy getters
    /// that assume it compiles. Pins the headroom `MAX_UNCHECKED_PATTERN` claims.
    #[test]
    fn test_longest_unchecked_pattern_compiles_lazily() {
        let long = "a".repeat(MAX_UNCHECKED_PATTERN);
        let scrubber = Scrubber::new(std::slice::from_ref(&long)).unwrap();
        let scrubbed = scrubber.scrub_text(&format!("{long}=hunter2"), "[FILTERED]");
        assert!(scrubbed.ends_with("=[FILTERED]"), "{scrubbed}");
    }

    #[test]
    fn test_key_match_is_case_insensitive_substring() {
        let scrubbed = scrub_text(r#"{"X-Api-Key-Header": "secret"}"#, &["api_key", "api-key"]);
        assert!(!scrubbed.contains("secret"), "{scrubbed}");
    }
}
