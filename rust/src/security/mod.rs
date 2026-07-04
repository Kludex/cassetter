pub mod body;
pub mod defaults;
pub mod headers;

use pyo3::prelude::*;

use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::HttpInteraction;
use crate::protocol::ws::WsInteraction;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct SecurityConfig {
    #[pyo3(get, set)]
    pub filter_headers: Vec<String>,
    #[pyo3(get, set)]
    pub filter_query_parameters: Vec<String>,
    #[pyo3(get, set)]
    pub body_scrub_patterns: Vec<String>,
    #[pyo3(get, set)]
    pub replacement: String,
}

#[pymethods]
impl SecurityConfig {
    #[new]
    #[pyo3(signature = (
        filter_headers=None,
        filter_query_parameters=None,
        body_scrub_patterns=None,
        replacement=None,
    ))]
    fn new(
        filter_headers: Option<Vec<String>>,
        filter_query_parameters: Option<Vec<String>>,
        body_scrub_patterns: Option<Vec<String>>,
        replacement: Option<String>,
    ) -> Self {
        SecurityConfig {
            filter_headers: filter_headers
                .unwrap_or_else(|| defaults::DEFAULT_FILTER_HEADERS.iter().map(|s| s.to_string()).collect()),
            filter_query_parameters: filter_query_parameters
                .unwrap_or_else(|| defaults::DEFAULT_FILTER_QUERY_PARAMS.iter().map(|s| s.to_string()).collect()),
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
    headers::filter_headers(&mut scrubbed.request.headers, &config.filter_headers);

    // Scrub response headers
    headers::filter_headers(&mut scrubbed.response.headers, &config.filter_headers);

    // Scrub query params from URI
    if let Some(new_uri) =
        headers::filter_query_params(&scrubbed.request.uri, &config.filter_query_parameters, &config.replacement)
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

/// Scrub a WebSocket interaction: remove sensitive headers from the handshake
/// and scrub sensitive patterns from text/JSON frame bodies.
#[pyfunction]
pub fn scrub_ws_interaction(interaction: &WsInteraction, config: &SecurityConfig) -> WsInteraction {
    let mut scrubbed = interaction.clone();
    headers::filter_headers(&mut scrubbed.headers, &config.filter_headers);
    for frame in &mut scrubbed.frames {
        frame.body = body::scrub_body(&frame.body, &config.body_scrub_patterns, &config.replacement);
    }
    scrubbed
}

/// Scrub a gRPC interaction: remove sensitive metadata from request and
/// response, and scrub sensitive patterns from the `json_debug` payload.
/// Binary protobuf bodies are stored as-is (they cannot be pattern-scrubbed).
#[pyfunction]
pub fn scrub_grpc_interaction(interaction: &GrpcInteraction, config: &SecurityConfig) -> GrpcInteraction {
    let mut scrubbed = interaction.clone();
    headers::filter_headers(&mut scrubbed.request.metadata, &config.filter_headers);
    headers::filter_headers(&mut scrubbed.response.metadata, &config.filter_headers);
    if let Some(debug) = &scrubbed.json_debug {
        scrubbed.json_debug = Some(body::scrub_json_value(
            debug,
            &config.body_scrub_patterns,
            &config.replacement,
        ));
    }
    scrubbed
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::protocol::grpc::{GrpcRequest, GrpcResponse};
    use crate::protocol::http::{Body, BodyContent};
    use crate::protocol::ws::WsFrame;

    fn default_config() -> SecurityConfig {
        SecurityConfig::new(None, None, None, None)
    }

    #[test]
    fn test_scrub_grpc_metadata_and_json_debug() {
        let mut request_metadata = HashMap::new();
        request_metadata.insert("authorization".to_string(), vec!["Bearer secret".to_string()]);
        request_metadata.insert("x-request-id".to_string(), vec!["abc".to_string()]);
        let mut response_metadata = HashMap::new();
        response_metadata.insert("set-cookie".to_string(), vec!["session=abc".to_string()]);

        let interaction = GrpcInteraction {
            request: GrpcRequest {
                method: "/pkg.Svc/M".to_string(),
                metadata: request_metadata,
                body: Body::binary(vec![1, 2]),
            },
            response: GrpcResponse {
                status_code: 0,
                status_message: "OK".to_string(),
                metadata: response_metadata,
                body: Body::binary(vec![3, 4]),
            },
            json_debug: Some(serde_json::json!({
                "request": {"password": "hunter2", "user": "alice"},
                "response": {"access_token": "tok_abc"}
            })),
            recorded_at: "2026-01-01T00:00:00Z".to_string(),
        };

        let scrubbed = scrub_grpc_interaction(&interaction, &default_config());

        assert!(!scrubbed.request.metadata.contains_key("authorization"));
        assert!(scrubbed.request.metadata.contains_key("x-request-id"));
        assert!(!scrubbed.response.metadata.contains_key("set-cookie"));
        let debug = scrubbed.json_debug.unwrap();
        assert_eq!(debug["request"]["password"], "[FILTERED]");
        assert_eq!(debug["request"]["user"], "alice");
        assert_eq!(debug["response"]["access_token"], "[FILTERED]");
        // Binary bodies are untouched
        assert_eq!(scrubbed.request.body, interaction.request.body);
    }

    #[test]
    fn test_scrub_ws_frame_bodies() {
        let interaction = WsInteraction {
            uri: "wss://api.example.com/v1".to_string(),
            headers: HashMap::new(),
            frames: vec![
                WsFrame {
                    direction: "send".to_string(),
                    frame_type: "text".to_string(),
                    body: Body::json(serde_json::json!({"access_token": "tok_abc", "channel": "ticker"})),
                    offset_ms: 0,
                },
                WsFrame {
                    direction: "recv".to_string(),
                    frame_type: "text".to_string(),
                    body: Body::text(r#"{"password": "secret", "ok": true}"#.to_string()),
                    offset_ms: 10,
                },
                WsFrame {
                    direction: "recv".to_string(),
                    frame_type: "binary".to_string(),
                    body: Body::binary(vec![1, 2, 3]),
                    offset_ms: 20,
                },
            ],
            recorded_at: "2026-01-01T00:00:00Z".to_string(),
        };

        let scrubbed = scrub_ws_interaction(&interaction, &default_config());

        match &scrubbed.frames[0].body.inner {
            BodyContent::Json(v) => {
                assert_eq!(v["access_token"], "[FILTERED]");
                assert_eq!(v["channel"], "ticker");
            }
            other => panic!("expected json body, got {other:?}"),
        }
        match &scrubbed.frames[1].body.inner {
            BodyContent::Text(t) => {
                assert!(t.contains(r#""password": "[FILTERED]""#));
                assert!(t.contains(r#""ok": true"#));
            }
            other => panic!("expected text body, got {other:?}"),
        }
        assert_eq!(scrubbed.frames[2].body, interaction.frames[2].body);
    }
}
