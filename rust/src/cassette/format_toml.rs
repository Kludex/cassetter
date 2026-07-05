use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::Cassette;
use crate::protocol::http::{Body, BodyContent, HttpInteraction, HttpRequest, HttpResponse};

/// TOML-compatible cassette format.
///
/// Body content is stored as a JSON string because TOML cannot represent
/// null values or heterogeneous arrays that JSON bodies may contain.
#[derive(Serialize, Deserialize)]
pub struct TomlCassette {
    pub version: u32,
    #[serde(default)]
    pub interactions: Vec<TomlInteraction>,
}

#[derive(Serialize, Deserialize)]
pub struct TomlInteraction {
    pub request: TomlRequest,
    pub response: TomlResponse,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recorded_at: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct TomlRequest {
    pub method: String,
    pub uri: String,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub body_content: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct TomlResponse {
    pub status: u16,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub body_content: Option<String>,
}

pub fn to_toml(cassette: &Cassette) -> TomlCassette {
    let interactions = cassette
        .interactions
        .iter()
        .map(|i| {
            let (req_type, req_content) = body_to_toml(&i.request.body);
            let (resp_type, resp_content) = body_to_toml(&i.response.body);
            TomlInteraction {
                request: TomlRequest {
                    method: i.request.method.clone(),
                    uri: i.request.uri.clone(),
                    headers: i.request.headers.clone(),
                    body_type: req_type,
                    body_content: req_content,
                },
                response: TomlResponse {
                    status: i.response.status,
                    headers: i.response.headers.clone(),
                    body_type: resp_type,
                    body_content: resp_content,
                },
                recorded_at: if i.recorded_at.is_empty() {
                    None
                } else {
                    Some(i.recorded_at.clone())
                },
            }
        })
        .collect();

    TomlCassette {
        version: cassette.version,
        interactions,
    }
}

pub fn from_toml(raw: TomlCassette) -> Cassette {
    let interactions: Vec<HttpInteraction> = raw
        .interactions
        .into_iter()
        .map(|i| {
            let request = HttpRequest {
                method: i.request.method,
                uri: i.request.uri,
                headers: i.request.headers,
                body: body_from_toml(&i.request.body_type, i.request.body_content),
            };
            let response = HttpResponse {
                status: i.response.status,
                headers: i.response.headers,
                body: body_from_toml(&i.response.body_type, i.response.body_content),
            };
            HttpInteraction {
                request,
                response,
                recorded_at: i.recorded_at.unwrap_or_default(),
            }
        })
        .collect();

    let played_indices = vec![false; interactions.len()];

    Cassette {
        version: raw.version,
        interactions,
        played_indices,
        grpc_interactions: Vec::new(),
        grpc_played: Vec::new(),
        ws_interactions: Vec::new(),
        ws_played: Vec::new(),
    }
}

fn body_to_toml(body: &Body) -> (String, Option<String>) {
    match &body.inner {
        BodyContent::Json(val) => (
            "json".to_string(),
            Some(serde_json::to_string(val).unwrap()),
        ),
        BodyContent::Text(s) => ("text".to_string(), Some(s.clone())),
        BodyContent::Binary(b) => ("binary".to_string(), Some(hex_encode(b))),
        BodyContent::None => ("none".to_string(), None),
    }
}

fn body_from_toml(body_type: &str, content: Option<String>) -> Body {
    match body_type {
        "json" => {
            if let Some(s) = content {
                if let Ok(val) = serde_json::from_str(&s) {
                    return Body::json(val);
                }
            }
            Body::none()
        }
        "text" => {
            if let Some(s) = content {
                Body::text(s)
            } else {
                Body::none()
            }
        }
        "binary" => {
            if let Some(s) = content {
                if let Ok(bytes) = hex_decode(&s) {
                    return Body::binary(bytes);
                }
            }
            Body::none()
        }
        _ => Body::none(),
    }
}

fn hex_encode(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    if !s.len().is_multiple_of(2) {
        return Err("invalid hex length".to_string());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| format!("hex decode error: {e}")))
        .collect()
}
