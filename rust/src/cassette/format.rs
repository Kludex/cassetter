use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::protocol::grpc::{GrpcInteraction, GrpcRequest, GrpcResponse};
use crate::protocol::http::{Body, BodyContent, HttpInteraction, HttpRequest, HttpResponse};
use crate::protocol::ws::{WsFrame, WsInteraction};

use super::Cassette;

/// Raw YAML structure - maps directly to the cassette file format.
/// Also accepts VCR-format cassettes on read (but never writes that format).
#[derive(Serialize, Deserialize)]
pub struct RawCassette {
    #[serde(default = "default_version")]
    pub version: u32,
    pub interactions: Vec<RawInteraction>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub grpc_interactions: Vec<RawGrpcInteraction>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub ws_interactions: Vec<RawWsInteraction>,
}

#[derive(Serialize, Deserialize)]
pub struct RawInteraction {
    pub request: RawRequest,
    pub response: RawResponse,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recorded_at: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct RawRequest {
    pub method: String,
    pub uri: String,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_body")]
    pub body: RawBody,
    /// Structured JSON body used by pydantic-ai style VCR serializers in
    /// place of `body`. Read-only compatibility - never written back out.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parsed_body: Option<serde_yaml::Value>,
}

#[derive(Serialize, Deserialize)]
pub struct RawResponse {
    #[serde(deserialize_with = "deserialize_status")]
    pub status: u16,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_body")]
    pub body: RawBody,
    /// See `RawRequest::parsed_body`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parsed_body: Option<serde_yaml::Value>,
}

#[derive(Serialize, Deserialize, Default)]
pub struct RawBody {
    #[serde(rename = "type", default = "default_none_type")]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<serde_yaml::Value>,
}

fn default_version() -> u32 {
    1
}

fn default_none_type() -> String {
    "none".to_string()
}

/// Deserialize status from either a plain integer (cassetter) or `{code: N, message: "..."}` (VCR).
fn deserialize_status<'de, D>(deserializer: D) -> Result<u16, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_yaml::Value::deserialize(deserializer)?;
    match &value {
        serde_yaml::Value::Number(n) => n
            .as_u64()
            .and_then(|v| u16::try_from(v).ok())
            .ok_or_else(|| serde::de::Error::custom("invalid status number")),
        serde_yaml::Value::Mapping(map) => {
            // VCR format: {code: 200, message: "OK"}
            let code_key = serde_yaml::Value::String("code".to_string());
            map.get(&code_key)
                .and_then(|v| v.as_u64())
                .and_then(|v| u16::try_from(v).ok())
                .ok_or_else(|| serde::de::Error::custom("VCR status missing 'code' field"))
        }
        _ => Err(serde::de::Error::custom("expected number or mapping for status")),
    }
}

/// Deserialize body from either cassetter format `{type: ..., content: ...}` or VCR format.
///
/// VCR body formats:
/// - `null` or missing -> none
/// - `""` (empty string) -> none
/// - `"raw string"` -> detect JSON or use text
/// - `{string: "..."}` -> detect JSON or use text
fn deserialize_body<'de, D>(deserializer: D) -> Result<RawBody, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_yaml::Value::deserialize(deserializer)?;
    match &value {
        serde_yaml::Value::Null => Ok(RawBody::default()),
        serde_yaml::Value::String(s) => Ok(vcr_string_to_raw_body(s)),
        serde_yaml::Value::Mapping(map) => {
            let type_key = serde_yaml::Value::String("type".to_string());
            let string_key = serde_yaml::Value::String("string".to_string());
            if map.contains_key(&type_key) {
                // Cassetter format - deserialize normally
                serde_yaml::from_value(value).map_err(serde::de::Error::custom)
            } else if let Some(string_val) = map.get(&string_key) {
                // VCR format: {string: "..."}
                match string_val {
                    serde_yaml::Value::Null => Ok(RawBody::default()),
                    serde_yaml::Value::String(s) => Ok(vcr_string_to_raw_body(s)),
                    _ => Ok(RawBody::default()),
                }
            } else {
                // Unknown mapping, treat as none
                Ok(RawBody::default())
            }
        }
        _ => Ok(RawBody::default()),
    }
}

/// Convert a VCR body string into a RawBody, detecting JSON content.
fn vcr_string_to_raw_body(s: &str) -> RawBody {
    if s.is_empty() {
        return RawBody::default();
    }
    // Try to parse as JSON
    if let Ok(json_val) = serde_json::from_str::<serde_json::Value>(s) {
        RawBody {
            body_type: "json".to_string(),
            content: Some(json_to_yaml(&json_val)),
        }
    } else {
        RawBody {
            body_type: "text".to_string(),
            content: Some(serde_yaml::Value::String(s.to_string())),
        }
    }
}

// --- gRPC raw types ---

#[derive(Serialize, Deserialize)]
pub struct RawGrpcInteraction {
    pub request: RawGrpcRequest,
    pub response: RawGrpcResponse,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub json_debug: Option<serde_yaml::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recorded_at: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct RawGrpcRequest {
    pub method: String,
    #[serde(default)]
    pub metadata: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub body: RawBody,
}

#[derive(Serialize, Deserialize)]
pub struct RawGrpcResponse {
    pub status_code: u32,
    #[serde(default = "default_ok")]
    pub status_message: String,
    #[serde(default)]
    pub metadata: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub body: RawBody,
}

fn default_ok() -> String {
    "OK".to_string()
}

// --- WebSocket raw types ---

#[derive(Serialize, Deserialize)]
pub struct RawWsInteraction {
    pub uri: String,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub frames: Vec<RawWsFrame>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recorded_at: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct RawWsFrame {
    pub direction: String,
    pub frame_type: String,
    #[serde(default)]
    pub body: RawBody,
    #[serde(default)]
    pub offset_ms: u64,
}

/// Convert raw YAML format to internal Cassette.
pub fn from_raw(raw: RawCassette) -> pyo3::PyResult<Cassette> {
    let interactions: Vec<HttpInteraction> = raw
        .interactions
        .into_iter()
        .map(|ri| {
            let request = HttpRequest {
                method: ri.request.method,
                uri: ri.request.uri,
                headers: ri.request.headers,
                body: match ri.request.parsed_body {
                    Some(v) => Body::json(yaml_to_json(v)),
                    None => body_from_raw(ri.request.body),
                },
            };
            let response = HttpResponse {
                status: ri.response.status,
                headers: ri.response.headers,
                body: match ri.response.parsed_body {
                    Some(v) => Body::json(yaml_to_json(v)),
                    None => body_from_raw(ri.response.body),
                },
            };
            HttpInteraction {
                request,
                response,
                recorded_at: ri.recorded_at.unwrap_or_default(),
            }
        })
        .collect();

    let grpc_interactions: Vec<GrpcInteraction> = raw
        .grpc_interactions
        .into_iter()
        .map(|ri| grpc_from_raw(ri))
        .collect();

    let ws_interactions: Vec<WsInteraction> = raw
        .ws_interactions
        .into_iter()
        .map(|ri| ws_from_raw(ri))
        .collect();

    let played_indices = vec![false; interactions.len()];
    let grpc_played = vec![false; grpc_interactions.len()];
    let ws_played = vec![false; ws_interactions.len()];

    Ok(Cassette {
        version: raw.version,
        interactions,
        played_indices,
        grpc_interactions,
        grpc_played,
        ws_interactions,
        ws_played,
    })
}

/// Convert internal Cassette to raw YAML format.
pub fn to_raw(cassette: &Cassette) -> RawCassette {
    let interactions = cassette
        .interactions
        .iter()
        .map(|i| RawInteraction {
            request: RawRequest {
                method: i.request.method.clone(),
                uri: i.request.uri.clone(),
                headers: i.request.headers.clone(),
                body: body_to_raw(&i.request.body),
                parsed_body: None,
            },
            response: RawResponse {
                status: i.response.status,
                headers: i.response.headers.clone(),
                body: body_to_raw(&i.response.body),
                parsed_body: None,
            },
            recorded_at: if i.recorded_at.is_empty() {
                None
            } else {
                Some(i.recorded_at.clone())
            },
        })
        .collect();

    let grpc_interactions = cassette
        .grpc_interactions
        .iter()
        .map(|i| grpc_to_raw(i))
        .collect();

    let ws_interactions = cassette
        .ws_interactions
        .iter()
        .map(|i| ws_to_raw(i))
        .collect();

    RawCassette {
        version: cassette.version,
        interactions,
        grpc_interactions,
        ws_interactions,
    }
}

fn grpc_from_raw(raw: RawGrpcInteraction) -> GrpcInteraction {
    let json_debug = raw.json_debug.map(yaml_to_json);
    GrpcInteraction {
        request: GrpcRequest {
            method: raw.request.method,
            metadata: raw.request.metadata,
            body: body_from_raw(raw.request.body),
        },
        response: GrpcResponse {
            status_code: raw.response.status_code,
            status_message: raw.response.status_message,
            metadata: raw.response.metadata,
            body: body_from_raw(raw.response.body),
        },
        json_debug,
        recorded_at: raw.recorded_at.unwrap_or_default(),
    }
}

fn grpc_to_raw(i: &GrpcInteraction) -> RawGrpcInteraction {
    RawGrpcInteraction {
        request: RawGrpcRequest {
            method: i.request.method.clone(),
            metadata: i.request.metadata.clone(),
            body: body_to_raw(&i.request.body),
        },
        response: RawGrpcResponse {
            status_code: i.response.status_code,
            status_message: i.response.status_message.clone(),
            metadata: i.response.metadata.clone(),
            body: body_to_raw(&i.response.body),
        },
        json_debug: i.json_debug.as_ref().map(json_to_yaml),
        recorded_at: if i.recorded_at.is_empty() {
            None
        } else {
            Some(i.recorded_at.clone())
        },
    }
}

fn ws_from_raw(raw: RawWsInteraction) -> WsInteraction {
    let frames = raw
        .frames
        .into_iter()
        .map(|f| WsFrame {
            direction: f.direction,
            frame_type: f.frame_type,
            body: body_from_raw(f.body),
            offset_ms: f.offset_ms,
        })
        .collect();
    WsInteraction {
        uri: raw.uri,
        headers: raw.headers,
        frames,
        recorded_at: raw.recorded_at.unwrap_or_default(),
    }
}

fn ws_to_raw(i: &WsInteraction) -> RawWsInteraction {
    let frames = i
        .frames
        .iter()
        .map(|f| RawWsFrame {
            direction: f.direction.clone(),
            frame_type: f.frame_type.clone(),
            body: body_to_raw(&f.body),
            offset_ms: f.offset_ms,
        })
        .collect();
    RawWsInteraction {
        uri: i.uri.clone(),
        headers: i.headers.clone(),
        frames,
        recorded_at: if i.recorded_at.is_empty() {
            None
        } else {
            Some(i.recorded_at.clone())
        },
    }
}

fn body_from_raw(raw: RawBody) -> Body {
    match raw.body_type.as_str() {
        "json" => {
            if let Some(content) = raw.content {
                let json_val = yaml_to_json(content);
                Body::json(json_val)
            } else {
                Body::none()
            }
        }
        "text" => {
            if let Some(serde_yaml::Value::String(s)) = raw.content {
                Body::text(s)
            } else {
                Body::none()
            }
        }
        "binary" => {
            if let Some(serde_yaml::Value::String(s)) = raw.content {
                match hex_decode(&s) {
                    Ok(bytes) => Body::binary(bytes),
                    Err(_) => Body::text(s),
                }
            } else {
                Body::none()
            }
        }
        _ => Body::none(),
    }
}

fn body_to_raw(body: &Body) -> RawBody {
    match &body.inner {
        BodyContent::Json(val) => RawBody {
            body_type: "json".to_string(),
            content: Some(json_to_yaml(val)),
        },
        BodyContent::Text(s) => RawBody {
            body_type: "text".to_string(),
            content: Some(serde_yaml::Value::String(s.clone())),
        },
        BodyContent::Binary(b) => RawBody {
            body_type: "binary".to_string(),
            content: Some(serde_yaml::Value::String(hex_encode(b))),
        },
        BodyContent::None => RawBody {
            body_type: "none".to_string(),
            content: None,
        },
    }
}

/// Convert serde_yaml::Value to serde_json::Value.
fn yaml_to_json(yaml: serde_yaml::Value) -> serde_json::Value {
    match yaml {
        serde_yaml::Value::Null => serde_json::Value::Null,
        serde_yaml::Value::Bool(b) => serde_json::Value::Bool(b),
        serde_yaml::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                serde_json::Value::Number(i.into())
            } else if let Some(f) = n.as_f64() {
                serde_json::Number::from_f64(f)
                    .map(serde_json::Value::Number)
                    .unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::Value::Null
            }
        }
        serde_yaml::Value::String(s) => serde_json::Value::String(s),
        serde_yaml::Value::Sequence(seq) => {
            serde_json::Value::Array(seq.into_iter().map(yaml_to_json).collect())
        }
        serde_yaml::Value::Mapping(map) => {
            let mut obj = serde_json::Map::new();
            for (k, v) in map {
                let key = match k {
                    serde_yaml::Value::String(s) => s,
                    other => format!("{other:?}"),
                };
                obj.insert(key, yaml_to_json(v));
            }
            serde_json::Value::Object(obj)
        }
        serde_yaml::Value::Tagged(tagged) => yaml_to_json(tagged.value),
    }
}

/// Convert serde_json::Value to serde_yaml::Value.
fn json_to_yaml(json: &serde_json::Value) -> serde_yaml::Value {
    match json {
        serde_json::Value::Null => serde_yaml::Value::Null,
        serde_json::Value::Bool(b) => serde_yaml::Value::Bool(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                serde_yaml::Value::Number(serde_yaml::Number::from(i))
            } else if let Some(f) = n.as_f64() {
                serde_yaml::Value::Number(serde_yaml::Number::from(f))
            } else {
                serde_yaml::Value::Null
            }
        }
        serde_json::Value::String(s) => serde_yaml::Value::String(s.clone()),
        serde_json::Value::Array(arr) => {
            serde_yaml::Value::Sequence(arr.iter().map(json_to_yaml).collect())
        }
        serde_json::Value::Object(map) => {
            let mut yaml_map = serde_yaml::Mapping::new();
            for (k, v) in map {
                yaml_map.insert(
                    serde_yaml::Value::String(k.clone()),
                    json_to_yaml(v),
                );
            }
            serde_yaml::Value::Mapping(yaml_map)
        }
    }
}

fn hex_encode(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("invalid hex length".to_string());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| {
            u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| format!("hex decode error: {e}"))
        })
        .collect()
}
