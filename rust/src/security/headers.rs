use std::collections::HashMap;

/// Remove filtered headers from a headers map (case-insensitive).
pub fn filter_headers(headers: &mut HashMap<String, Vec<String>>, filtered: &[String]) {
    let filtered_lower: Vec<String> = filtered.iter().map(|h| h.to_lowercase()).collect();
    headers.retain(|key, _| !filtered_lower.contains(&key.to_lowercase()));
}

/// Replace filtered query parameter values in a URI.
/// Returns None if no changes were made.
///
/// Both the query string and the fragment are scrubbed: the OAuth implicit
/// flow returns `access_token` in the fragment, so scrubbing only the query
/// would record the credential verbatim.
///
/// Operates on the raw segments to preserve the original encoding of
/// unfiltered parameters (e.g. commas stay as `,` instead of `%2C`).
pub fn filter_query_params(uri: &str, filtered: &[String], replacement: &str) -> Option<String> {
    let fragment_start = uri.find('#');
    let query_start = match fragment_start {
        Some(hash) => uri[..hash].find('?'),
        None => uri.find('?'),
    };
    if query_start.is_none() && fragment_start.is_none() {
        return None;
    }

    let filtered_lower: Vec<String> = filtered.iter().map(|p| p.to_lowercase()).collect();
    let mut changed = false;

    let base_end = query_start.or(fragment_start).unwrap_or(uri.len());
    let mut out = String::with_capacity(uri.len());
    out.push_str(&uri[..base_end]);

    if let Some(start) = query_start {
        let end = fragment_start.unwrap_or(uri.len());
        out.push('?');
        out.push_str(&filter_pairs(
            &uri[start + 1..end],
            &filtered_lower,
            replacement,
            &mut changed,
        ));
    }

    if let Some(start) = fragment_start {
        out.push('#');
        out.push_str(&filter_pairs(
            &uri[start + 1..],
            &filtered_lower,
            replacement,
            &mut changed,
        ));
    }

    changed.then_some(out)
}

/// Scrub an `a=1&b=2` segment, leaving anything that is not a pair untouched.
fn filter_pairs(
    raw: &str,
    filtered_lower: &[String],
    replacement: &str,
    changed: &mut bool,
) -> String {
    if raw.is_empty() {
        return String::new();
    }
    raw.split('&')
        .map(|pair| {
            if let Some(eq) = pair.find('=') {
                let key = &pair[..eq];
                // Percent-decode the key for case-insensitive comparison
                let decoded_key = percent_decode(key);
                if filtered_lower.contains(&decoded_key.to_lowercase()) {
                    *changed = true;
                    return format!("{key}={replacement}");
                }
            }
            pair.to_string()
        })
        .collect::<Vec<_>>()
        .join("&")
}

/// Decode percent-encoded bytes in a query key/value.
fn percent_decode(input: &str) -> String {
    let mut result = Vec::with_capacity(input.len());
    let bytes = input.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = [bytes[i + 1], bytes[i + 2]];
            if hex.iter().all(u8::is_ascii_hexdigit) {
                let text = std::str::from_utf8(&hex).expect("hex digits are ASCII");
                if let Ok(byte) = u8::from_str_radix(text, 16) {
                    result.push(byte);
                    i += 3;
                    continue;
                }
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
        headers.insert(
            "Content-Type".to_string(),
            vec!["application/json".to_string()],
        );
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
        let result = filter_query_params(uri, &["api_key".to_string()], "[FILTERED]");
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

    #[test]
    fn test_filter_fragment_params() {
        // OAuth implicit flow returns the token in the fragment.
        let uri = "https://app.example.com/callback#access_token=sk-live-DEADBEEF&state=xyz";
        let result = filter_query_params(uri, &["access_token".to_string()], "[FILTERED]");
        let new_uri = result.expect("fragment should be scrubbed");
        assert!(!new_uri.contains("sk-live-DEADBEEF"), "{new_uri}");
        assert!(new_uri.contains("state=xyz"), "{new_uri}");
    }

    #[test]
    fn test_filter_query_and_fragment_together() {
        let uri = "https://app.example.com/cb?api_key=secret&keep=1#access_token=tok&frag=2";
        let result = filter_query_params(
            uri,
            &["api_key".to_string(), "access_token".to_string()],
            "[FILTERED]",
        );
        let new_uri = result.expect("both segments should be scrubbed");
        assert!(!new_uri.contains("secret"), "{new_uri}");
        assert!(!new_uri.contains("=tok"), "{new_uri}");
        assert!(
            new_uri.contains("keep=1") && new_uri.contains("frag=2"),
            "{new_uri}"
        );
    }

    #[test]
    fn test_plain_fragment_is_untouched() {
        let uri = "https://example.com/docs?api_key=secret#section-3";
        let new_uri =
            filter_query_params(uri, &["api_key".to_string()], "[FILTERED]").expect("changed");
        assert_eq!(
            new_uri,
            "https://example.com/docs?api_key=[FILTERED]#section-3"
        );
    }
}
