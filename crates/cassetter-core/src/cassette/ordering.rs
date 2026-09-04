use crate::matching::config::MatchConfig;
use crate::matching::matchers::filter_json_paths;
use crate::protocol::http::{BodyContent, HttpInteraction, HttpRequest};

/// Check that `order` writes every interaction exactly once.
///
/// The serializers skip an index they cannot resolve, so an order that is
/// short, repeats, or points past the end would quietly drop or duplicate
/// recorded interactions instead of failing.
pub(crate) fn validate(order: &[usize], count: usize) -> Result<(), String> {
    let mut written = vec![false; count];
    for &idx in order {
        match written.get_mut(idx) {
            None => {
                return Err(format!(
                    "interaction index {idx} out of range for {count} interactions"
                ))
            }
            Some(true) => return Err(format!("interaction index {idx} appears more than once")),
            Some(slot) => *slot = true,
        }
    }
    if order.len() != count {
        return Err(format!(
            "order covers {} of {count} interactions",
            order.len()
        ));
    }
    Ok(())
}

/// The order interactions are written to disk in.
///
/// Recording order follows whichever response arrived first, so two runs of the
/// same concurrent suite produce different files. Sorting by the fields the
/// matcher compares makes the file canonical without changing what replays:
/// replay takes the first unplayed match, so only interactions that can match
/// the same request carry order, and those are equal under the sort key and
/// left in `tie_break` order by a stable sort.
pub(crate) fn output_order(
    interactions: &[HttpInteraction],
    config: Option<&MatchConfig>,
    tie_break: &[usize],
) -> Vec<usize> {
    let mut order: Vec<usize> = (0..interactions.len()).collect();
    if tie_break.len() == interactions.len() {
        order.sort_by_key(|&idx| tie_break[idx]);
    }
    if let Some(config) = config {
        order.sort_by_cached_key(|&idx| sort_key(&interactions[idx].request, config));
    }
    order
}

/// A deterministic key built from the fields `config` matches by equality.
///
/// `headers` is left out: it matches a recorded subset of the incoming headers,
/// so two different header sets can both match one request and must keep their
/// recorded order. The key must never separate requests the matcher considers
/// equal - collisions merely leave order untouched, which is always safe.
fn sort_key(request: &HttpRequest, config: &MatchConfig) -> Vec<String> {
    let mut key = Vec::with_capacity(config.match_on.len());
    for matcher in &config.match_on {
        match matcher.as_str() {
            "method" => key.push(request.method.to_uppercase()),
            "uri" => key.push(request.uri.clone()),
            "body" => key.push(canonical_body(&request.body.inner, &[])),
            "json_body" => key.push(canonical_body(
                &request.body.inner,
                &config.ignore_json_paths,
            )),
            _ => {}
        }
    }
    key
}

fn canonical_body(content: &BodyContent, ignore_paths: &[String]) -> String {
    match content {
        BodyContent::Json(value) => {
            let mut out = String::new();
            write_canonical(&filter_json_paths(value, ignore_paths, ""), &mut out);
            out
        }
        BodyContent::Text(text) => text.clone(),
        BodyContent::Binary(bytes) => bytes.iter().map(|b| format!("{b:02x}")).collect(),
        BodyContent::None => String::new(),
    }
}

/// Serialize with object keys sorted.
///
/// `serde_json` preserves the recorded key order, and JSON objects compare
/// equal regardless of it, so an insertion-order key would separate two bodies
/// the matcher treats as identical.
fn write_canonical(value: &serde_json::Value, out: &mut String) {
    match value {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push_str(&serde_json::Value::String((*key).clone()).to_string());
                out.push(':');
                write_canonical(&map[key.as_str()], out);
            }
            out.push('}');
        }
        serde_json::Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        other => out.push_str(&other.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::protocol::http::{Body, HttpResponse};

    fn interaction(method: &str, uri: &str, body: Body) -> HttpInteraction {
        HttpInteraction {
            request: HttpRequest {
                method: method.to_string(),
                uri: uri.to_string(),
                headers: HashMap::new(),
                body,
            },
            response: HttpResponse {
                status: 200,
                headers: HashMap::new(),
                body: Body::none(),
            },
            recorded_at: String::new(),
        }
    }

    fn json_body(raw: &str) -> Body {
        Body {
            inner: BodyContent::Json(serde_json::from_str(raw).unwrap()),
        }
    }

    fn config(match_on: &[&str], ignore: &[&str]) -> MatchConfig {
        MatchConfig {
            match_on: match_on.iter().map(|s| s.to_string()).collect(),
            ignore_json_paths: ignore.iter().map(|s| s.to_string()).collect(),
        }
    }

    #[test]
    fn sorts_by_uri() {
        let interactions = vec![
            interaction("GET", "https://example.com/b", Body::none()),
            interaction("GET", "https://example.com/a", Body::none()),
        ];
        let order = output_order(&interactions, Some(&config(&["method", "uri"], &[])), &[]);
        assert_eq!(order, vec![1, 0]);
    }

    #[test]
    fn keeps_recorded_order_for_indistinguishable_interactions() {
        let interactions = vec![
            interaction("POST", "https://example.com/c", json_body(r#"{"q": "z"}"#)),
            interaction("POST", "https://example.com/c", json_body(r#"{"q": "a"}"#)),
        ];
        // The body is not matched on, so these two are interchangeable at
        // replay and their order is what picks the response.
        let order = output_order(&interactions, Some(&config(&["method", "uri"], &[])), &[]);
        assert_eq!(order, vec![0, 1]);
    }

    #[test]
    fn sorts_by_body_when_it_is_matched_on() {
        let interactions = vec![
            interaction("POST", "https://example.com/c", json_body(r#"{"q": "z"}"#)),
            interaction("POST", "https://example.com/c", json_body(r#"{"q": "a"}"#)),
        ];
        let order = output_order(
            &interactions,
            Some(&config(&["method", "uri", "json_body"], &[])),
            &[],
        );
        assert_eq!(order, vec![1, 0]);
    }

    #[test]
    fn ignored_json_paths_do_not_separate_equal_bodies() {
        let interactions = vec![
            interaction(
                "POST",
                "https://example.com/c",
                json_body(r#"{"q":1,"id":"z"}"#),
            ),
            interaction(
                "POST",
                "https://example.com/c",
                json_body(r#"{"q":1,"id":"a"}"#),
            ),
        ];
        let order = output_order(
            &interactions,
            Some(&config(&["method", "uri", "json_body"], &["id"])),
            &[],
        );
        assert_eq!(order, vec![0, 1]);
    }

    #[test]
    fn json_key_order_does_not_separate_equal_bodies() {
        let interactions = vec![
            interaction(
                "POST",
                "https://example.com/c",
                json_body(r#"{"b":1,"a":2}"#),
            ),
            interaction(
                "POST",
                "https://example.com/c",
                json_body(r#"{"a":2,"b":1}"#),
            ),
        ];
        let order = output_order(
            &interactions,
            Some(&config(&["method", "uri", "json_body"], &[])),
            &[],
        );
        assert_eq!(order, vec![0, 1]);
    }

    #[test]
    fn headers_never_key_the_sort() {
        let mut first = interaction("GET", "https://example.com/a", Body::none());
        first
            .request
            .headers
            .insert("x-trace".to_string(), vec!["zzz".to_string()]);
        let second = interaction("GET", "https://example.com/a", Body::none());
        let interactions = vec![first, second];
        let order = output_order(
            &interactions,
            Some(&config(&["method", "uri", "headers"], &[])),
            &[],
        );
        assert_eq!(order, vec![0, 1]);
    }

    #[test]
    fn method_case_does_not_separate_equal_requests() {
        let interactions = vec![
            interaction("get", "https://example.com/b", Body::none()),
            interaction("GET", "https://example.com/a", Body::none()),
        ];
        let order = output_order(&interactions, Some(&config(&["method", "uri"], &[])), &[]);
        assert_eq!(order, vec![1, 0]);
    }

    #[test]
    fn tie_break_reorders_before_sorting() {
        let interactions = vec![
            interaction("POST", "https://example.com/c", Body::none()),
            interaction("POST", "https://example.com/c", Body::none()),
        ];
        let order = output_order(
            &interactions,
            Some(&config(&["method", "uri"], &[])),
            &[1, 0],
        );
        assert_eq!(order, vec![1, 0]);
    }

    #[test]
    fn tie_break_alone_orders_without_a_config() {
        let interactions = vec![
            interaction("GET", "https://example.com/b", Body::none()),
            interaction("GET", "https://example.com/a", Body::none()),
        ];
        let order = output_order(&interactions, None, &[1, 0]);
        assert_eq!(order, vec![1, 0]);
    }

    #[test]
    fn validate_accepts_a_permutation() {
        assert!(validate(&[2, 0, 1], 3).is_ok());
        assert!(validate(&[], 0).is_ok());
    }

    #[test]
    fn validate_rejects_an_out_of_range_index() {
        let err = validate(&[0, 2], 2).unwrap_err();
        assert!(err.to_string().contains("out of range"), "{err}");
    }

    #[test]
    fn validate_rejects_a_repeated_index() {
        let err = validate(&[0, 0], 2).unwrap_err();
        assert!(err.to_string().contains("more than once"), "{err}");
    }

    #[test]
    fn validate_rejects_a_short_order() {
        let err = validate(&[0], 2).unwrap_err();
        assert!(err.to_string().contains("covers 1 of 2"), "{err}");
    }

    #[test]
    fn mismatched_tie_break_is_ignored() {
        let interactions = vec![
            interaction("GET", "https://example.com/b", Body::none()),
            interaction("GET", "https://example.com/a", Body::none()),
        ];
        let order = output_order(&interactions, None, &[0]);
        assert_eq!(order, vec![0, 1]);
    }
}
