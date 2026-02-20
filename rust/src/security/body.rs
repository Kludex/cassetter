use crate::protocol::http::{Body, BodyContent};

/// Scrub sensitive patterns from a Body.
pub fn scrub_body(body: &Body, patterns: &[String], replacement: &str) -> Body {
    match &body.inner {
        BodyContent::Json(value) => {
            let scrubbed = scrub_json_value(value, patterns, replacement);
            Body::json(scrubbed)
        }
        BodyContent::Text(text) => {
            let scrubbed = scrub_text(text, patterns, replacement);
            Body::text(scrubbed)
        }
        BodyContent::Binary(_) | BodyContent::None => body.clone(),
    }
}

/// Scrub JSON values: replace values of keys that match sensitive patterns.
fn scrub_json_value(
    value: &serde_json::Value,
    patterns: &[String],
    replacement: &str,
) -> serde_json::Value {
    match value {
        serde_json::Value::Object(map) => {
            let mut new_map = serde_json::Map::new();
            for (key, val) in map {
                let key_lower = key.to_lowercase();
                if patterns.iter().any(|p| key_lower.contains(&p.to_lowercase())) {
                    new_map.insert(key.clone(), serde_json::Value::String(replacement.to_string()));
                } else {
                    new_map.insert(key.clone(), scrub_json_value(val, patterns, replacement));
                }
            }
            serde_json::Value::Object(new_map)
        }
        serde_json::Value::Array(arr) => {
            serde_json::Value::Array(arr.iter().map(|v| scrub_json_value(v, patterns, replacement)).collect())
        }
        _ => value.clone(),
    }
}

/// Scrub sensitive patterns from plain text.
fn scrub_text(text: &str, patterns: &[String], replacement: &str) -> String {
    let mut result = text.to_string();
    for pattern in patterns {
        // Replace "key": "value" or key=value patterns
        let re_json =
            regex::Regex::new(&format!(r#"("{}"\s*:\s*)"[^"]*""#, regex::escape(pattern))).unwrap();
        result = re_json
            .replace_all(&result, format!(r#"${{1}}"{replacement}""#))
            .to_string();

        let re_form =
            regex::Regex::new(&format!(r#"({}=)[^&\s]*"#, regex::escape(pattern))).unwrap();
        result = re_form
            .replace_all(&result, format!("${{1}}{replacement}"))
            .to_string();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scrub_json_body() {
        let value = serde_json::json!({
            "username": "alice",
            "password": "secret123",
            "nested": {
                "access_token": "tok_abc",
                "data": "keep"
            }
        });
        let patterns = vec!["password".to_string(), "access_token".to_string()];
        let scrubbed = scrub_json_value(&value, &patterns, "[FILTERED]");

        assert_eq!(scrubbed["password"], "[FILTERED]");
        assert_eq!(scrubbed["nested"]["access_token"], "[FILTERED]");
        assert_eq!(scrubbed["username"], "alice");
        assert_eq!(scrubbed["nested"]["data"], "keep");
    }

    #[test]
    fn test_scrub_text_json_pattern() {
        let text = r#"{"password": "secret", "name": "alice"}"#;
        let scrubbed = scrub_text(text, &["password".to_string()], "[FILTERED]");
        assert!(scrubbed.contains(r#""password": "[FILTERED]""#));
        assert!(scrubbed.contains(r#""name": "alice""#));
    }

    #[test]
    fn test_scrub_text_form_pattern() {
        let text = "grant_type=password&password=secret&username=alice";
        let scrubbed = scrub_text(text, &["password".to_string()], "[FILTERED]");
        assert!(scrubbed.contains("password=[FILTERED]"));
        assert!(scrubbed.contains("username=alice"));
    }
}
