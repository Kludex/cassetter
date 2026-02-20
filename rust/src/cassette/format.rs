use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::protocol::http::{Body, BodyContent, HttpInteraction, HttpRequest, HttpResponse};

use super::Cassette;

/// Raw YAML structure - maps directly to the cassette file format.
#[derive(Serialize, Deserialize)]
pub struct RawCassette {
    pub version: u32,
    pub interactions: Vec<RawInteraction>,
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
    #[serde(default)]
    pub body: RawBody,
}

#[derive(Serialize, Deserialize)]
pub struct RawResponse {
    pub status: u16,
    #[serde(default)]
    pub headers: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub body: RawBody,
}

#[derive(Serialize, Deserialize, Default)]
pub struct RawBody {
    #[serde(rename = "type", default = "default_none_type")]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<serde_yaml::Value>,
}

fn default_none_type() -> String {
    "none".to_string()
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
                body: body_from_raw(ri.request.body),
            };
            let response = HttpResponse {
                status: ri.response.status,
                headers: ri.response.headers,
                body: body_from_raw(ri.response.body),
            };
            HttpInteraction {
                request,
                response,
                recorded_at: ri.recorded_at.unwrap_or_default(),
            }
        })
        .collect();

    let played_indices = vec![false; interactions.len()];

    Ok(Cassette {
        version: raw.version,
        interactions,
        played_indices,
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
            },
            response: RawResponse {
                status: i.response.status,
                headers: i.response.headers.clone(),
                body: body_to_raw(&i.response.body),
            },
            recorded_at: if i.recorded_at.is_empty() {
                None
            } else {
                Some(i.recorded_at.clone())
            },
        })
        .collect();

    RawCassette {
        version: cassette.version,
        interactions,
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
