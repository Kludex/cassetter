pub mod body;
pub mod defaults;
pub mod headers;

use pyo3::prelude::*;

use crate::protocol::http::HttpInteraction;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct SecurityConfig {
    #[pyo3(get, set)]
    pub filtered_headers: Vec<String>,
    #[pyo3(get, set)]
    pub filtered_query_params: Vec<String>,
    #[pyo3(get, set)]
    pub body_scrub_patterns: Vec<String>,
    #[pyo3(get, set)]
    pub replacement: String,
}

#[pymethods]
impl SecurityConfig {
    #[new]
    #[pyo3(signature = (
        filtered_headers=None,
        filtered_query_params=None,
        body_scrub_patterns=None,
        replacement=None,
    ))]
    fn new(
        filtered_headers: Option<Vec<String>>,
        filtered_query_params: Option<Vec<String>>,
        body_scrub_patterns: Option<Vec<String>>,
        replacement: Option<String>,
    ) -> Self {
        SecurityConfig {
            filtered_headers: filtered_headers
                .unwrap_or_else(|| defaults::DEFAULT_FILTERED_HEADERS.iter().map(|s| s.to_string()).collect()),
            filtered_query_params: filtered_query_params
                .unwrap_or_else(|| defaults::DEFAULT_FILTERED_QUERY_PARAMS.iter().map(|s| s.to_string()).collect()),
            body_scrub_patterns: body_scrub_patterns
                .unwrap_or_else(|| defaults::DEFAULT_BODY_SCRUB_PATTERNS.iter().map(|s| s.to_string()).collect()),
            replacement: replacement.unwrap_or_else(|| "[FILTERED]".to_string()),
        }
    }
}

/// Scrub an interaction: remove sensitive headers, query params, and body patterns.
#[pyfunction]
pub fn scrub_interaction(
    interaction: &HttpInteraction,
    config: &SecurityConfig,
) -> HttpInteraction {
    let mut scrubbed = interaction.clone();

    // Scrub request headers
    headers::filter_headers(&mut scrubbed.request.headers, &config.filtered_headers);

    // Scrub response headers
    headers::filter_headers(&mut scrubbed.response.headers, &config.filtered_headers);

    // Scrub query params from URI
    if let Some(new_uri) =
        headers::filter_query_params(&scrubbed.request.uri, &config.filtered_query_params, &config.replacement)
    {
        scrubbed.request.uri = new_uri;
    }

    // Scrub request body
    scrubbed.request.body =
        body::scrub_body(&scrubbed.request.body, &config.body_scrub_patterns, &config.replacement);

    // Scrub response body
    scrubbed.response.body =
        body::scrub_body(&scrubbed.response.body, &config.body_scrub_patterns, &config.replacement);

    scrubbed
}
