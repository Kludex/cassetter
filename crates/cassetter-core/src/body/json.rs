/// Check if a content-type header indicates JSON.
pub fn is_json_content_type(content_type: &str) -> bool {
    let media_type = content_type
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    media_type == "application/json"
        || media_type
            .split_once('/')
            .is_some_and(|(_, subtype)| subtype.ends_with("+json"))
}

/// Parse bytes as JSON.
pub fn parse_json(data: &[u8]) -> Result<serde_json::Value, serde_json::Error> {
    serde_json::from_slice(data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_json_content_types() {
        assert!(is_json_content_type("application/json"));
        assert!(is_json_content_type("application/json; charset=utf-8"));
        assert!(is_json_content_type("application/vnd.api+json"));
        assert!(is_json_content_type("application/ld+json"));
        assert!(is_json_content_type(
            " application/problem+json ; charset=utf-8"
        ));
        assert!(!is_json_content_type("application/jsonp"));
        assert!(!is_json_content_type("text/plain; profile=+json"));
        assert!(!is_json_content_type("text/html"));
        assert!(!is_json_content_type("application/xml"));
    }

    #[test]
    fn test_parse_json() {
        let data = br#"{"key": "value"}"#;
        let val = parse_json(data).unwrap();
        assert_eq!(val["key"], "value");
    }
}
