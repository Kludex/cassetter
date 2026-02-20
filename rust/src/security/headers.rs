use std::collections::HashMap;

use url::Url;

/// Remove filtered headers from a headers map (case-insensitive).
pub fn filter_headers(headers: &mut HashMap<String, Vec<String>>, filtered: &[String]) {
    let filtered_lower: Vec<String> = filtered.iter().map(|h| h.to_lowercase()).collect();
    headers.retain(|key, _| !filtered_lower.contains(&key.to_lowercase()));
}

/// Replace filtered query parameter values in a URI.
/// Returns None if no changes were made.
pub fn filter_query_params(uri: &str, filtered: &[String], replacement: &str) -> Option<String> {
    let mut parsed = match Url::parse(uri) {
        Ok(u) => u,
        Err(_) => return None,
    };

    let filtered_lower: Vec<String> = filtered.iter().map(|p| p.to_lowercase()).collect();

    let original_query = parsed.query().map(|q| q.to_string());
    let pairs: Vec<(String, String)> = parsed
        .query_pairs()
        .map(|(k, v)| {
            if filtered_lower.contains(&k.to_lowercase()) {
                (k.to_string(), replacement.to_string())
            } else {
                (k.to_string(), v.to_string())
            }
        })
        .collect();

    if pairs.is_empty() {
        return None;
    }

    parsed.query_pairs_mut().clear().extend_pairs(&pairs);

    let new_query = parsed.query().map(|q| q.to_string());
    if original_query == new_query {
        None
    } else {
        Some(parsed.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_filter_headers() {
        let mut headers = HashMap::new();
        headers.insert("Authorization".to_string(), vec!["Bearer abc".to_string()]);
        headers.insert("Content-Type".to_string(), vec!["application/json".to_string()]);
        headers.insert("X-Api-Key".to_string(), vec!["secret".to_string()]);

        filter_headers(
            &mut headers,
            &["authorization".to_string(), "x-api-key".to_string()],
        );

        assert_eq!(headers.len(), 1);
        assert!(headers.contains_key("Content-Type"));
    }

    #[test]
    fn test_filter_query_params() {
        let uri = "https://api.example.com/v1/data?api_key=secret&format=json";
        let result = filter_query_params(
            uri,
            &["api_key".to_string()],
            "[FILTERED]",
        );
        assert!(result.is_some());
        let new_uri = result.unwrap();
        assert!(new_uri.contains("api_key=%5BFILTERED%5D"));
        assert!(new_uri.contains("format=json"));
    }

    #[test]
    fn test_no_query_params() {
        let uri = "https://api.example.com/v1/data";
        let result = filter_query_params(uri, &["api_key".to_string()], "[FILTERED]");
        assert!(result.is_none());
    }
}
