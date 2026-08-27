pub mod body;
pub mod defaults;
pub mod headers;

use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::HttpInteraction;
use crate::protocol::ws::WsInteraction;
use crate::{CassetteError, Result};

/// Placeholder written in place of a filtered value.
pub const DEFAULT_REPLACEMENT: &str = "[FILTERED]";

#[derive(Clone, Debug)]
pub struct SecurityConfig {
    pub filter_headers: Vec<String>,
    pub filter_query_parameters: Vec<String>,
    pub body_scrub_patterns: Vec<String>,
    pub replacement: String,
    /// Compiled form of `body_scrub_patterns`, rebuilt whenever it is set.
    pub scrubber: body::Scrubber,
}

fn compile_scrubber(patterns: &[String]) -> Result<body::Scrubber> {
    body::Scrubber::new(patterns)
        .map_err(|e| CassetteError::Value(format!("invalid body scrub pattern: {e}")))
}

/// Add `extra` to the built-in list rather than standing in for it.
///
/// Naming one more header to scrub is never a request to start recording the
/// eight that were already covered, so the defaults always survive. Assign to
/// the field afterwards to define the list outright.
pub fn extend_defaults(defaults: &[&str], extra: Option<Vec<String>>) -> Vec<String> {
    let mut merged: Vec<String> = defaults.iter().map(|s| s.to_string()).collect();
    for value in extra.unwrap_or_default() {
        // All three lists are compared case-insensitively, so dedupe that way too.
        if !merged.iter().any(|kept| kept.eq_ignore_ascii_case(&value)) {
            merged.push(value);
        }
    }
    merged
}

impl SecurityConfig {
    pub fn new(
        filter_headers: Option<Vec<String>>,
        filter_query_parameters: Option<Vec<String>>,
        body_scrub_patterns: Option<Vec<String>>,
        replacement: Option<String>,
    ) -> Result<Self> {
        let body_scrub_patterns =
            extend_defaults(defaults::DEFAULT_BODY_SCRUB_PATTERNS, body_scrub_patterns);
        Ok(SecurityConfig {
            filter_headers: extend_defaults(defaults::DEFAULT_FILTER_HEADERS, filter_headers),
            filter_query_parameters: extend_defaults(
                defaults::DEFAULT_FILTER_QUERY_PARAMS,
                filter_query_parameters,
            ),
            scrubber: compile_scrubber(&body_scrub_patterns)?,
            body_scrub_patterns,
            replacement: replacement.unwrap_or_else(|| DEFAULT_REPLACEMENT.to_string()),
        })
    }

    pub fn set_body_scrub_patterns(&mut self, patterns: Vec<String>) -> Result<()> {
        self.scrubber = compile_scrubber(&patterns)?;
        self.body_scrub_patterns = patterns;
        Ok(())
    }

    /// Build a config from the built-in lists alone.
    pub fn with_defaults() -> Self {
        SecurityConfig::new(None, None, None, None).expect("default patterns compile")
    }

    pub fn describe(&self) -> String {
        format!(
            "SecurityConfig(filter_headers={:?}, filter_query_parameters={:?}, body_scrub_patterns={:?}, replacement={:?})",
            self.filter_headers,
            self.filter_query_parameters,
            self.body_scrub_patterns,
            self.replacement,
        )
    }
}

impl Default for SecurityConfig {
    fn default() -> Self {
        SecurityConfig::with_defaults()
    }
}

/// Scrub an interaction: remove sensitive headers, query params, and body patterns.
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
    if let Some(new_uri) = headers::filter_query_params(
        &scrubbed.request.uri,
        &config.filter_query_parameters,
        &config.replacement,
    ) {
        scrubbed.request.uri = new_uri;
    }

    // Scrub request body
    scrubbed.request.body = config
        .scrubber
        .scrub_body(&scrubbed.request.body, &config.replacement);

    // Scrub response body
    scrubbed.response.body = config
        .scrubber
        .scrub_body(&scrubbed.response.body, &config.replacement);

    scrubbed
}

/// Scrub a WebSocket interaction: remove sensitive headers from the handshake
/// and scrub sensitive patterns from text/JSON frame bodies.
pub fn scrub_ws_interaction(interaction: &WsInteraction, config: &SecurityConfig) -> WsInteraction {
    let mut scrubbed = interaction.clone();
    headers::filter_headers(&mut scrubbed.headers, &config.filter_headers);
    for frame in &mut scrubbed.frames {
        frame.body = config.scrubber.scrub_body(&frame.body, &config.replacement);
    }
    scrubbed
}

/// Scrub a gRPC interaction: remove sensitive metadata from request and
/// response, and scrub sensitive patterns from the `json_debug` payload.
/// Binary protobuf bodies are stored as-is (they cannot be pattern-scrubbed).
pub fn scrub_grpc_interaction(
    interaction: &GrpcInteraction,
    config: &SecurityConfig,
) -> GrpcInteraction {
    let mut scrubbed = interaction.clone();
    headers::filter_headers(&mut scrubbed.request.metadata, &config.filter_headers);
    headers::filter_headers(&mut scrubbed.response.metadata, &config.filter_headers);
    if let Some(debug) = &scrubbed.json_debug {
        scrubbed.json_debug = Some(config.scrubber.scrub_json_value(debug, &config.replacement));
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
        SecurityConfig::with_defaults()
    }

    #[test]
    fn test_scrub_grpc_metadata_and_json_debug() {
        let mut request_metadata = HashMap::new();
        request_metadata.insert(
            "authorization".to_string(),
            vec!["Bearer secret".to_string()],
        );
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
                    body: Body::json(
                        serde_json::json!({"access_token": "tok_abc", "channel": "ticker"}),
                    ),
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
                // A text frame that parses as JSON is scrubbed as a tree and
                // re-serialized, so spacing is serde_json's rather than the
                // sender's. Only bodies that actually changed are rewritten.
                assert!(t.contains(r#""password":"[FILTERED]""#), "{t}");
                assert!(t.contains(r#""ok":true"#), "{t}");
            }
            other => panic!("expected text body, got {other:?}"),
        }
        assert_eq!(scrubbed.frames[2].body, interaction.frames[2].body);
    }
}
