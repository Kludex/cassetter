use std::collections::HashMap;

/// Remove filtered headers from a headers map (case-insensitive).
pub fn filter_headers(headers: &mut HashMap<String, Vec<String>>, filtered: &[String]) {
    let filtered_lower: Vec<String> = filtered.iter().map(|h| h.to_lowercase()).collect();
    headers.retain(|key, _| !filtered_lower.contains(&key.to_lowercase()));
}

/// Replace filtered query parameter values in a URI.
/// Returns None if no changes were made.
///
/// Operates on the raw query string to preserve the original encoding of
/// unfiltered parameters (e.g. commas stay as `,` instead of `%2C`).
pub fn filter_query_params(uri: &str, filtered: &[String], replacement: &str) -> Option<String> {
    let query_start = uri.find('?')?;
    let raw_query = &uri[query_start + 1..];
    if raw_query.is_empty() {
        return None;
    }

    let filtered_lower: Vec<String> = filtered.iter().map(|p| p.to_lowercase()).collect();

    let mut changed = false;
    let new_query: String = raw_query
        .split('&')
        .map(|pair| {
            if let Some(eq) = pair.find('=') {
                let key = &pair[..eq];
                // Percent-decode the key for case-insensitive comparison
                let decoded_key = percent_decode(key);
                if filtered_lower.contains(&decoded_key.to_lowercase()) {
                    changed = true;
                    return format!("{key}={replacement}");
                }
            }
            pair.to_string()
        })
        .collect::<Vec<_>>()
        .join("&");

    if !changed {
        return None;
    }

    Some(format!("{}?{}", &uri[..query_start], new_query))
}

/// Decode percent-encoded bytes in a query key/value.
fn percent_decode(input: &str) -> String {
    let mut result = Vec::with_capacity(input.len());
    let bytes = input.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(byte) = u8::from_str_radix(&input[i + 1..i + 3], 16) {
                result.push(byte);
                i += 3;
                continue;
            }
        }
        result.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&result).into_owned()
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
        assert!(new_uri.contains("api_key=[FILTERED]"));
        assert!(new_uri.contains("format=json"));
    }

    #[test]
    fn test_filter_query_params_preserves_comma() {
        // When filtering a *different* param, the unfiltered param with a comma
        // must keep its original encoding (literal comma, not %2C).
        let uri = "https://httpbin.org/get?product=123,456&api_key=secret";
        let result = filter_query_params(uri, &["api_key".to_string()], "[FILTERED]");
        assert!(result.is_some());
        let new_uri = result.unwrap();
        assert!(
            new_uri.contains("product=123,456"),
            "comma was re-encoded: {new_uri}"
        );
    }

    #[test]
    fn test_no_query_params() {
        let uri = "https://api.example.com/v1/data";
        let result = filter_query_params(uri, &["api_key".to_string()], "[FILTERED]");
        assert!(result.is_none());
    }
}
