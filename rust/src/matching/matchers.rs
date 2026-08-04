use crate::protocol::http::{BodyContent, HttpRequest};

pub fn match_method(incoming: &HttpRequest, recorded: &HttpRequest) -> bool {
    incoming.method.eq_ignore_ascii_case(&recorded.method)
}

pub fn match_uri(incoming: &HttpRequest, recorded: &HttpRequest) -> bool {
    incoming.uri == recorded.uri
}

pub fn match_headers(incoming: &HttpRequest, recorded: &HttpRequest) -> bool {
    // All recorded headers must be present in incoming (subset match)
    for (key, values) in &recorded.headers {
        match incoming.headers.get(key) {
            Some(incoming_values) => {
                if incoming_values != values {
                    return false;
                }
            }
            None => {
                // Also check case-insensitive
                let key_lower = key.to_lowercase();
                let found = incoming
                    .headers
                    .iter()
                    .find(|(k, _)| k.to_lowercase() == key_lower);
                match found {
                    Some((_, v)) if v == values => {}
                    _ => return false,
                }
            }
        }
    }
    true
}

pub fn match_body(incoming: &HttpRequest, recorded: &HttpRequest) -> bool {
    incoming.body == recorded.body
}

/// Match JSON bodies, ignoring specified JSON paths.
pub fn match_json_body(
    incoming: &HttpRequest,
    recorded: &HttpRequest,
    ignore_paths: &[String],
) -> bool {
    match (&incoming.body.inner, &recorded.body.inner) {
        (BodyContent::Json(a), BodyContent::Json(b)) => {
            let a_filtered = filter_json_paths(a, ignore_paths, "");
            let b_filtered = filter_json_paths(b, ignore_paths, "");
            a_filtered == b_filtered
        }
        _ => match_body(incoming, recorded),
    }
}

/// Remove specified paths from a JSON value for comparison.
pub(crate) fn filter_json_paths(
    value: &serde_json::Value,
    ignore_paths: &[String],
    current_path: &str,
) -> serde_json::Value {
    if ignore_paths.iter().any(|p| p == current_path) {
        return serde_json::Value::Null;
    }

    match value {
        serde_json::Value::Object(map) => {
            let mut filtered = serde_json::Map::new();
            for (key, val) in map {
                let path = if current_path.is_empty() {
                    key.clone()
                } else {
                    format!("{current_path}.{key}")
                };
                if !ignore_paths.iter().any(|p| p == &path) {
                    filtered.insert(key.clone(), filter_json_paths(val, ignore_paths, &path));
                }
            }
            serde_json::Value::Object(filtered)
        }
        serde_json::Value::Array(arr) => serde_json::Value::Array(
            arr.iter()
                .enumerate()
                .map(|(i, v)| {
                    let path = format!("{current_path}[{i}]");
                    filter_json_paths(v, ignore_paths, &path)
                })
                .collect(),
        ),
        _ => value.clone(),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::protocol::http::Body;

    use super::*;

    fn req(method: &str, uri: &str) -> HttpRequest {
        HttpRequest {
            method: method.to_string(),
            uri: uri.to_string(),
            headers: HashMap::new(),
            body: Body::none(),
        }
    }

    #[test]
    fn test_match_method() {
        assert!(match_method(&req("GET", "/"), &req("get", "/")));
        assert!(!match_method(&req("GET", "/"), &req("POST", "/")));
    }

    #[test]
    fn test_match_uri() {
        assert!(match_uri(
            &req("GET", "https://example.com/api"),
            &req("GET", "https://example.com/api")
        ));
        assert!(!match_uri(
            &req("GET", "https://example.com/api"),
            &req("GET", "https://example.com/other")
        ));
    }

    #[test]
    fn test_match_json_body_with_ignore() {
        let a = HttpRequest {
            method: "POST".to_string(),
            uri: "/api".to_string(),
            headers: HashMap::new(),
            body: Body::json(serde_json::json!({
                "data": "hello",
                "timestamp": "2026-01-01",
                "request_id": "abc123"
            })),
        };
        let b = HttpRequest {
            method: "POST".to_string(),
            uri: "/api".to_string(),
            headers: HashMap::new(),
            body: Body::json(serde_json::json!({
                "data": "hello",
                "timestamp": "2026-02-02",
                "request_id": "xyz789"
            })),
        };

        // Without ignoring - should not match
        assert!(!match_json_body(&a, &b, &[]));

        // Ignoring timestamp and request_id - should match
        assert!(match_json_body(
            &a,
            &b,
            &["timestamp".to_string(), "request_id".to_string()]
        ));
    }
}
