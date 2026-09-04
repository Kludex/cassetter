use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use super::Cassette;
use crate::protocol::http::{Body, BodyContent, HttpInteraction, HttpRequest, HttpResponse};
use crate::{CassetteError, Result};

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
    pub headers: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub body_content: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct TomlResponse {
    pub status: u16,
    #[serde(default)]
    pub headers: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub body_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub body_content: Option<String>,
}

pub fn to_toml(cassette: &Cassette, order: &[usize]) -> TomlCassette {
    let interactions = order
        .iter()
        .filter_map(|&idx| cassette.interactions.get(idx))
        .map(|i| {
            let (req_type, req_content) = body_to_toml(&i.request.body);
            let (resp_type, resp_content) = body_to_toml(&i.response.body);
            TomlInteraction {
                request: TomlRequest {
                    method: i.request.method.clone(),
                    uri: i.request.uri.clone(),
                    headers: sorted(&i.request.headers),
                    body_type: req_type,
                    body_content: req_content,
                },
                response: TomlResponse {
                    status: i.response.status,
                    headers: sorted(&i.response.headers),
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

pub fn from_toml(raw: TomlCassette) -> Result<Cassette> {
    let interactions: Vec<HttpInteraction> = raw
        .interactions
        .into_iter()
        .enumerate()
        .map(|(index, i)| {
            let request_body = body_from_toml(&i.request.body_type, i.request.body_content)
                .map_err(|error| {
                    CassetteError::Format(format!(
                        "invalid TOML request body in interaction {index}: {error}"
                    ))
                })?;
            let response_body = body_from_toml(&i.response.body_type, i.response.body_content)
                .map_err(|error| {
                    CassetteError::Format(format!(
                        "invalid TOML response body in interaction {index}: {error}"
                    ))
                })?;
            let request = HttpRequest {
                method: i.request.method,
                uri: i.request.uri,
                headers: i.request.headers.into_iter().collect(),
                body: request_body,
            };
            let response = HttpResponse {
                status: i.response.status,
                headers: i.response.headers.into_iter().collect(),
                body: response_body,
            };
            Ok(HttpInteraction {
                request,
                response,
                recorded_at: i.recorded_at.unwrap_or_default(),
            })
        })
        .collect::<Result<_>>()?;

    let played_indices = vec![false; interactions.len()];

    Ok(Cassette {
        version: raw.version,
        interactions,
        played_indices,
        ..Cassette::default()
    })
}

/// Order headers deterministically for serialization.
fn sorted(
    headers: &std::collections::HashMap<String, Vec<String>>,
) -> BTreeMap<String, Vec<String>> {
    headers
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect()
}

fn body_to_toml(body: &Body) -> (String, Option<String>) {
    match &body.inner {
        BodyContent::Json(val) => (
            "json".to_string(),
            Some(serde_json::to_string(val).unwrap()),
        ),
        BodyContent::Text(s) => ("text".to_string(), Some(s.clone())),
        BodyContent::Binary(b) => ("binary".to_string(), Some(crate::body::hex::encode(b))),
        BodyContent::None => ("none".to_string(), None),
    }
}

fn body_from_toml(body_type: &str, content: Option<String>) -> Result<Body> {
    match (body_type, content) {
        ("json", Some(content)) => serde_json::from_str(&content)
            .map(Body::json)
            .map_err(|error| CassetteError::Format(format!("invalid JSON content: {error}"))),
        ("text", Some(content)) => Ok(Body::text(content)),
        ("binary", Some(content)) => crate::body::hex::decode(&content)
            .map(Body::binary)
            .map_err(|error| CassetteError::Format(format!("invalid binary content: {error}"))),
        (_, None) => Ok(Body::none()),
        (body_type, Some(_)) => Err(CassetteError::Format(format!(
            "unsupported body type: {body_type}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_malformed_json_request_body() {
        let error = Cassette::from_toml(
            r#"
version = 1

[[interactions]]
[interactions.request]
method = "POST"
uri = "https://example.com"
body_type = "json"
body_content = "{"

[interactions.response]
status = 200
body_type = "none"
"#,
        )
        .unwrap_err();

        assert!(
            error
                .to_string()
                .contains("invalid TOML request body in interaction 0"),
            "{error}"
        );
    }

    #[test]
    fn rejects_malformed_binary_response_body() {
        let error = Cassette::from_toml(
            r#"
version = 1

[[interactions]]
[interactions.request]
method = "GET"
uri = "https://example.com"
body_type = "none"

[interactions.response]
status = 200
body_type = "binary"
body_content = "xyz"
"#,
        )
        .unwrap_err();

        assert!(
            error
                .to_string()
                .contains("invalid TOML response body in interaction 0"),
            "{error}"
        );
    }

    #[test]
    fn rejects_unsupported_body_type_with_content() {
        let error = Cassette::from_toml(
            r#"
version = 1

[[interactions]]
[interactions.request]
method = "POST"
uri = "https://example.com"
body_type = "xml"
body_content = "<message>hello</message>"

[interactions.response]
status = 200
body_type = "none"
"#,
        )
        .unwrap_err();

        assert!(
            error
                .to_string()
                .contains("invalid TOML request body in interaction 0: unsupported body type: xml"),
            "{error}"
        );
    }

    #[test]
    fn accepts_declared_body_without_content_as_none() {
        let cassette = Cassette::from_toml(
            r#"
version = 1

[[interactions]]
[interactions.request]
method = "POST"
uri = "https://example.com"
body_type = "json"

[interactions.response]
status = 200
body_type = "binary"
"#,
        )
        .unwrap();

        assert_eq!(cassette.interactions[0].request.body, Body::none());
        assert_eq!(cassette.interactions[0].response.body, Body::none());
    }
}
