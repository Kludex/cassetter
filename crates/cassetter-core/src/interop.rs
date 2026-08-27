//! Plain-JSON representations of core types.
//!
//! Bindings that exchange structured data with their host language (rather
//! than wrapping every type in a native class) convert through here. The
//! shapes match the cassette file format: bodies are `{type, content}` and
//! binary content is hex, so the file on disk and every language binding share
//! one data representation.

use std::collections::HashMap;

use serde_json::{json, Map, Value};

use crate::body::hex;
use crate::matching::config::MatchConfig;
use crate::protocol::grpc::{GrpcInteraction, GrpcRequest, GrpcResponse};
use crate::protocol::http::{Body, BodyContent, HttpInteraction, HttpRequest, HttpResponse};
use crate::protocol::ws::{WsFrame, WsInteraction};
use crate::security::SecurityConfig;
use crate::Result;

// --- Body ---

pub fn body_to_json(body: &Body) -> Value {
    match &body.inner {
        BodyContent::Json(v) => json!({ "type": "json", "content": v }),
        BodyContent::Text(s) => json!({ "type": "text", "content": s }),
        BodyContent::Binary(b) => json!({ "type": "binary", "content": hex::encode(b) }),
        BodyContent::None => json!({ "type": "none" }),
    }
}

pub fn body_from_json(v: &Value) -> Body {
    let body_type = v.get("type").and_then(Value::as_str).unwrap_or("none");
    let content = v.get("content");
    match body_type {
        "json" => content.map(|c| Body::json(c.clone())).unwrap_or_default(),
        "text" => content
            .and_then(Value::as_str)
            .map(|s| Body::text(s.to_string()))
            .unwrap_or_default(),
        "binary" => content
            .and_then(Value::as_str)
            .and_then(|s| hex::decode(s).ok())
            .map(Body::binary)
            .unwrap_or_default(),
        _ => Body::none(),
    }
}

// --- Headers ---

fn headers_to_json(headers: &HashMap<String, Vec<String>>) -> Value {
    let mut map = Map::new();
    for (k, v) in headers {
        map.insert(
            k.clone(),
            Value::Array(v.iter().map(|s| json!(s)).collect()),
        );
    }
    Value::Object(map)
}

fn headers_from_json(v: Option<&Value>) -> HashMap<String, Vec<String>> {
    let mut out = HashMap::new();
    if let Some(Value::Object(map)) = v {
        for (k, vals) in map {
            let list = match vals {
                Value::Array(items) => items
                    .iter()
                    .filter_map(|i| i.as_str().map(str::to_string))
                    .collect(),
                Value::String(s) => vec![s.clone()],
                _ => Vec::new(),
            };
            out.insert(k.clone(), list);
        }
    }
    out
}

fn str_field(v: &Value, key: &str) -> String {
    v.get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

// --- HTTP ---

pub fn request_to_json(r: &HttpRequest) -> Value {
    json!({
        "method": r.method,
        "uri": r.uri,
        "headers": headers_to_json(&r.headers),
        "body": body_to_json(&r.body),
    })
}

pub fn request_from_json(v: &Value) -> HttpRequest {
    HttpRequest {
        method: str_field(v, "method"),
        uri: str_field(v, "uri"),
        headers: headers_from_json(v.get("headers")),
        body: v.get("body").map(body_from_json).unwrap_or_default(),
    }
}

pub fn response_to_json(r: &HttpResponse) -> Value {
    json!({
        "status": r.status,
        "headers": headers_to_json(&r.headers),
        "body": body_to_json(&r.body),
    })
}

pub fn response_from_json(v: &Value) -> HttpResponse {
    HttpResponse {
        status: v.get("status").and_then(Value::as_u64).unwrap_or(0) as u16,
        headers: headers_from_json(v.get("headers")),
        body: v.get("body").map(body_from_json).unwrap_or_default(),
    }
}

pub fn interaction_to_json(i: &HttpInteraction) -> Value {
    json!({
        "request": request_to_json(&i.request),
        "response": response_to_json(&i.response),
        "recordedAt": i.recorded_at,
    })
}

pub fn interaction_from_json(v: &Value) -> HttpInteraction {
    HttpInteraction {
        request: v
            .get("request")
            .map(request_from_json)
            .unwrap_or_else(|| HttpRequest::new(String::new(), String::new(), None, None)),
        response: v
            .get("response")
            .map(response_from_json)
            .unwrap_or_else(|| HttpResponse::new(0, None, None)),
        recorded_at: str_field(v, "recordedAt"),
    }
}

// --- gRPC ---

pub fn grpc_interaction_to_json(i: &GrpcInteraction) -> Value {
    json!({
        "request": {
            "method": i.request.method,
            "metadata": headers_to_json(&i.request.metadata),
            "body": body_to_json(&i.request.body),
        },
        "response": {
            "statusCode": i.response.status_code,
            "statusMessage": i.response.status_message,
            "metadata": headers_to_json(&i.response.metadata),
            "body": body_to_json(&i.response.body),
        },
        "recordedAt": i.recorded_at,
        "jsonDebug": i.json_debug,
    })
}

pub fn grpc_interaction_from_json(v: &Value) -> GrpcInteraction {
    let req = v.get("request");
    let resp = v.get("response");
    GrpcInteraction {
        request: GrpcRequest {
            method: req.map(|r| str_field(r, "method")).unwrap_or_default(),
            metadata: headers_from_json(req.and_then(|r| r.get("metadata"))),
            body: req
                .and_then(|r| r.get("body"))
                .map(body_from_json)
                .unwrap_or_default(),
        },
        response: GrpcResponse {
            status_code: resp
                .and_then(|r| r.get("statusCode"))
                .and_then(Value::as_u64)
                .unwrap_or(0) as u32,
            status_message: resp
                .and_then(|r| r.get("statusMessage"))
                .and_then(Value::as_str)
                .unwrap_or("OK")
                .to_string(),
            metadata: headers_from_json(resp.and_then(|r| r.get("metadata"))),
            body: resp
                .and_then(|r| r.get("body"))
                .map(body_from_json)
                .unwrap_or_default(),
        },
        json_debug: v.get("jsonDebug").filter(|d| !d.is_null()).cloned(),
        recorded_at: str_field(v, "recordedAt"),
    }
}

// --- WebSocket ---

pub fn ws_interaction_to_json(i: &WsInteraction) -> Value {
    json!({
        "uri": i.uri,
        "headers": headers_to_json(&i.headers),
        "frames": i.frames.iter().map(|f| json!({
            "direction": f.direction,
            "frameType": f.frame_type,
            "body": body_to_json(&f.body),
            "offsetMs": f.offset_ms,
        })).collect::<Vec<_>>(),
        "recordedAt": i.recorded_at,
    })
}

pub fn ws_interaction_from_json(v: &Value) -> WsInteraction {
    let frames = v
        .get("frames")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .map(|f| WsFrame {
                    direction: str_field(f, "direction"),
                    frame_type: str_field(f, "frameType"),
                    body: f.get("body").map(body_from_json).unwrap_or_default(),
                    offset_ms: f.get("offsetMs").and_then(Value::as_u64).unwrap_or(0),
                })
                .collect()
        })
        .unwrap_or_default();

    WsInteraction {
        uri: str_field(v, "uri"),
        headers: headers_from_json(v.get("headers")),
        frames,
        recorded_at: str_field(v, "recordedAt"),
    }
}

// --- Config ---

fn string_list(v: Option<&Value>) -> Option<Vec<String>> {
    match v {
        Some(Value::Array(items)) => Some(
            items
                .iter()
                .filter_map(|i| i.as_str().map(str::to_string))
                .collect(),
        ),
        _ => None,
    }
}

pub fn match_config_from_json(v: &Value) -> Result<MatchConfig> {
    MatchConfig::new(
        string_list(v.get("matchOn")),
        string_list(v.get("ignoreJsonPaths")),
    )
}

/// Build a security config. As in Python, the lists here *extend* the built-in
/// defaults rather than standing in for them.
pub fn security_config_from_json(v: &Value) -> Result<SecurityConfig> {
    SecurityConfig::new(
        string_list(v.get("filterHeaders")),
        string_list(v.get("filterQueryParameters")),
        string_list(v.get("bodyScrubPatterns")),
        v.get("replacement")
            .and_then(Value::as_str)
            .map(str::to_string),
    )
}
