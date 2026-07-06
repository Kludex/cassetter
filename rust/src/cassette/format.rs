use std::collections::{BTreeMap, HashMap};

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;

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
    #[serde(default)]
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
    #[serde(default, deserialize_with = "deserialize_headers")]
    pub headers: BTreeMap<String, Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_body")]
    pub body: RawBody,
    /// Structured JSON body used by pydantic-ai style VCR serializers in
    /// place of `body`. Read-only compatibility - never written back out.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parsed_body: Option<Value>,
}

#[derive(Serialize, Deserialize)]
pub struct RawResponse {
    #[serde(deserialize_with = "deserialize_status")]
    pub status: u16,
    #[serde(default, deserialize_with = "deserialize_headers")]
    pub headers: BTreeMap<String, Vec<String>>,
    #[serde(default, deserialize_with = "deserialize_body")]
    pub body: RawBody,
    /// See `RawRequest::parsed_body`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parsed_body: Option<Value>,
}

#[derive(Serialize, Deserialize, Default)]
pub struct RawBody {
    #[serde(rename = "type", default = "default_none_type")]
    pub body_type: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        serialize_with = "serialize_yaml_safe_opt"
    )]
    pub content: Option<Value>,
}

/// Serialize a JSON value, force-quoting strings that serde-saphyr's
/// auto-selected block scalars cannot round-trip (whitespace/newline-only
/// strings, e.g. an LLM response token that is just "\n").
struct YamlSafeValue<'a>(&'a Value);

impl serde::Serialize for YamlSafeValue<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self.0 {
            Value::String(s) if is_blank_multiline(s) => {
                serde_saphyr::DoubleQuoted(s.as_str()).serialize(serializer)
            }
            Value::Array(items) => serializer.collect_seq(items.iter().map(YamlSafeValue)),
            Value::Object(map) => {
                serializer.collect_map(map.iter().map(|(k, v)| (k, YamlSafeValue(v))))
            }
            other => other.serialize(serializer),
        }
    }
}

fn is_blank_multiline(s: &str) -> bool {
    s.contains('\n') && s.chars().all(|c| matches!(c, '\n' | ' ' | '\t'))
}

fn serialize_yaml_safe_opt<S: serde::Serializer>(
    value: &Option<Value>,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    // Only invoked when Some thanks to skip_serializing_if.
    YamlSafeValue(value.as_ref().expect("skip_serializing_if guards None")).serialize(serializer)
}

fn default_version() -> u32 {
    1
}

fn default_none_type() -> String {
    "none".to_string()
}

// --- !!binary extraction ---
//
// PyYAML stores byte values in VCR cassettes as `!!binary` block scalars.
// serde-saphyr rejects non-UTF-8 binary in string positions and serde is
// single-shot, so binary payloads are extracted from the raw text before
// parsing: each block is base64-decoded into a side table and replaced with
// a sentinel scalar, which `from_raw` resolves back to bytes.

const BINARY_SENTINEL_PREFIX: &str = "__cassetter@binary@scalar@";

fn binary_sentinel(index: usize) -> String {
    format!("{BINARY_SENTINEL_PREFIX}{index}__")
}

fn sentinel_index(s: &str) -> Option<usize> {
    s.strip_prefix(BINARY_SENTINEL_PREFIX)?
        .strip_suffix("__")?
        .parse()
        .ok()
}

fn line_indent(line: &str) -> usize {
    line.len() - line.trim_start().len()
}

/// Extract `!!binary` block scalars from YAML text.
///
/// Returns the rewritten text (each block replaced by a sentinel scalar) and
/// the decoded payloads. Only the block form PyYAML emits (`... !!binary |`
/// at end of line) is rewritten, which cannot appear inside a quoted scalar.
pub fn extract_binary_scalars(content: &str) -> (String, Vec<Vec<u8>>) {
    if !content.contains("!!binary") {
        return (content.to_string(), Vec::new());
    }
    let mut out: Vec<String> = Vec::new();
    let mut binaries: Vec<Vec<u8>> = Vec::new();
    let lines: Vec<&str> = content.lines().collect();
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        let trimmed = line.trim_end();
        let is_binary_block = trimmed.ends_with("!!binary |")
            || trimmed.ends_with("!!binary |-")
            || trimmed.ends_with("!!binary |+");
        if is_binary_block {
            if let Some(pos) = line.rfind("!!binary ") {
                let node_indent = line_indent(line);
                let mut b64 = String::new();
                let mut j = i + 1;
                // Blank lines are legal inside block scalars and contribute
                // nothing to base64; only consume them when more block
                // content follows, so trailing blanks stay with the parent.
                let mut pending_blanks = 0usize;
                while j < lines.len() {
                    let content_line = lines[j];
                    if content_line.trim().is_empty() {
                        pending_blanks += 1;
                        j += 1;
                        continue;
                    }
                    if line_indent(content_line) <= node_indent {
                        break;
                    }
                    pending_blanks = 0;
                    b64.push_str(content_line.trim());
                    j += 1;
                }
                j -= pending_blanks;
                if let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(&b64) {
                    out.push(format!(
                        "{}{}",
                        &line[..pos],
                        binary_sentinel(binaries.len())
                    ));
                    binaries.push(bytes);
                    i = j;
                    continue;
                }
            }
        }
        out.push(line.to_string());
        i += 1;
    }
    (out.join("\n"), binaries)
}

/// Deserialize status from either a plain integer (cassetter) or `{code: N, message: "..."}` (VCR).
fn deserialize_status<'de, D>(deserializer: D) -> Result<u16, D::Error>
where
    D: serde::Deserializer<'de>,
{
    struct StatusVisitor;

    impl<'de> serde::de::Visitor<'de> for StatusVisitor {
        type Value = u16;

        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "a status number or a VCR {{code, message}} mapping")
        }

        fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<u16, E> {
            u16::try_from(v).map_err(|_| E::custom("invalid status number"))
        }

        fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<u16, E> {
            u16::try_from(v).map_err(|_| E::custom("invalid status number"))
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(self, mut map: A) -> Result<u16, A::Error> {
            let mut code: Option<u16> = None;
            while let Some(key) = map.next_key::<String>()? {
                if key == "code" {
                    code = Some(map.next_value::<u16>()?);
                } else {
                    map.next_value::<serde::de::IgnoredAny>()?;
                }
            }
            code.ok_or_else(|| serde::de::Error::custom("VCR status missing 'code' field"))
        }
    }

    deserializer.deserialize_any(StatusVisitor)
}

const KNOWN_BODY_TYPES: &[&str] = &["json", "text", "binary", "none"];

/// Deserialize body from either cassetter format `{type: ..., content: ...}` or VCR format.
///
/// VCR body formats:
/// - `null` or missing -> none
/// - `""` (empty string) -> none
/// - `"raw string"` -> detect JSON or use text
/// - `{string: "..."}` -> detect JSON or use text
/// - `{string: !!binary ...}` -> binary (via sentinel extraction)
/// - any other mapping -> structured JSON body (aiohttp-recorded shape)
fn deserialize_body<'de, D>(deserializer: D) -> Result<RawBody, D::Error>
where
    D: serde::Deserializer<'de>,
{
    struct BodyVisitor;

    impl<'de> serde::de::Visitor<'de> for BodyVisitor {
        type Value = RawBody;

        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "a body string, mapping, or null")
        }

        fn visit_unit<E: serde::de::Error>(self) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_none<E: serde::de::Error>(self) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<RawBody, E> {
            Ok(vcr_string_to_raw_body(v))
        }

        fn visit_bool<E: serde::de::Error>(self, _: bool) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_u64<E: serde::de::Error>(self, _: u64) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_i64<E: serde::de::Error>(self, _: i64) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_f64<E: serde::de::Error>(self, _: f64) -> Result<RawBody, E> {
            Ok(RawBody::default())
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(
            self,
            mut access: A,
        ) -> Result<RawBody, A::Error> {
            let mut map = serde_json::Map::new();
            while let Some(key) = access.next_key::<String>()? {
                let value = access.next_value::<Value>()?;
                map.insert(key, value);
            }
            // A mapping shaped exactly like cassetter's envelope is treated as
            // the envelope. This is ambiguous with a bare JSON payload whose
            // keys are exactly {type, content} with a known type value, but no
            // cassette-level discriminator exists (VCR files also carry a
            // top-level version), and preferring the payload interpretation
            // would corrupt every cassetter-format body instead of this one
            // rare shape. Documented in the migration guide.
            let is_cassetter_body = map
                .get("type")
                .and_then(|v| v.as_str())
                .is_some_and(|t| KNOWN_BODY_TYPES.contains(&t))
                && map.keys().all(|k| k == "type" || k == "content");
            if is_cassetter_body {
                let body_type = map["type"].as_str().expect("checked above").to_string();
                Ok(RawBody {
                    body_type,
                    content: map.remove("content"),
                })
            } else if let Some(string_val) = map.get("string") {
                // VCR format: {string: "..."}
                match string_val {
                    Value::Null => Ok(RawBody::default()),
                    Value::String(s) => Ok(vcr_string_to_raw_body(s)),
                    _ => Ok(RawBody::default()),
                }
            } else {
                // Bare mapping: a structured JSON body recorded directly
                // (e.g. aiohttp-recorded request bodies)
                Ok(RawBody {
                    body_type: "json".to_string(),
                    content: Some(Value::Object(map)),
                })
            }
        }
    }

    deserializer.deserialize_any(BodyVisitor)
}

/// Deserialize a header map, tolerating scalar (non-sequence) and
/// number/bool values.
fn deserialize_headers<'de, D>(deserializer: D) -> Result<BTreeMap<String, Vec<String>>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    struct HeaderScalar(Option<String>);

    impl<'de> serde::Deserialize<'de> for HeaderScalar {
        fn deserialize<D2: serde::Deserializer<'de>>(d: D2) -> Result<Self, D2::Error> {
            struct V;
            impl<'de> serde::de::Visitor<'de> for V {
                type Value = HeaderScalar;

                fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                    write!(f, "a header value")
                }

                fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v.to_string())))
                }

                fn visit_string<E: serde::de::Error>(self, v: String) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v)))
                }

                fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v.to_string())))
                }

                fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v.to_string())))
                }

                fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v.to_string())))
                }

                fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(Some(v.to_string())))
                }

                fn visit_unit<E: serde::de::Error>(self) -> Result<HeaderScalar, E> {
                    Ok(HeaderScalar(None))
                }

                fn visit_map<A: serde::de::MapAccess<'de>>(
                    self,
                    mut access: A,
                ) -> Result<HeaderScalar, A::Error> {
                    while access
                        .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>()?
                        .is_some()
                    {}
                    Ok(HeaderScalar(None))
                }

                fn visit_seq<A: serde::de::SeqAccess<'de>>(
                    self,
                    mut access: A,
                ) -> Result<HeaderScalar, A::Error> {
                    while access.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                    Ok(HeaderScalar(None))
                }
            }
            d.deserialize_any(V)
        }
    }

    struct HeaderValues(Vec<String>);

    impl<'de> serde::Deserialize<'de> for HeaderValues {
        fn deserialize<D2: serde::Deserializer<'de>>(d: D2) -> Result<Self, D2::Error> {
            struct V;
            impl<'de> serde::de::Visitor<'de> for V {
                type Value = HeaderValues;

                fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                    write!(f, "a header value or list of header values")
                }

                fn visit_seq<A: serde::de::SeqAccess<'de>>(
                    self,
                    mut access: A,
                ) -> Result<HeaderValues, A::Error> {
                    let mut out = Vec::with_capacity(access.size_hint().unwrap_or(1));
                    while let Some(HeaderScalar(item)) = access.next_element()? {
                        if let Some(s) = item {
                            out.push(s);
                        }
                    }
                    Ok(HeaderValues(out))
                }

                fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v.to_string()]))
                }

                fn visit_string<E: serde::de::Error>(self, v: String) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v]))
                }

                fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v.to_string()]))
                }

                fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v.to_string()]))
                }

                fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v.to_string()]))
                }

                fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(vec![v.to_string()]))
                }

                fn visit_unit<E: serde::de::Error>(self) -> Result<HeaderValues, E> {
                    Ok(HeaderValues(Vec::new()))
                }
            }
            d.deserialize_any(V)
        }
    }

    struct HeadersVisitor;

    impl<'de> serde::de::Visitor<'de> for HeadersVisitor {
        type Value = BTreeMap<String, Vec<String>>;

        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "a header mapping")
        }

        fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
            Ok(BTreeMap::new())
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(
            self,
            mut access: A,
        ) -> Result<Self::Value, A::Error> {
            let mut headers = BTreeMap::new();
            while let Some((name, HeaderValues(values))) =
                access.next_entry::<String, HeaderValues>()?
            {
                headers.insert(name, values);
            }
            Ok(headers)
        }
    }

    deserializer.deserialize_any(HeadersVisitor)
}

/// Convert a VCR body string into a RawBody, detecting JSON content.
fn vcr_string_to_raw_body(s: &str) -> RawBody {
    if s.is_empty() {
        return RawBody::default();
    }
    if sentinel_index(s).is_some() {
        // Placeholder for an extracted `!!binary` scalar, resolved in from_raw.
        return RawBody {
            body_type: "text".to_string(),
            content: Some(Value::String(s.to_string())),
        };
    }
    // Try to parse as JSON
    if let Ok(json_val) = serde_json::from_str::<Value>(s) {
        RawBody {
            body_type: "json".to_string(),
            content: Some(json_val),
        }
    } else {
        RawBody {
            body_type: "text".to_string(),
            content: Some(Value::String(s.to_string())),
        }
    }
}

// --- gRPC raw types ---

#[derive(Serialize, Deserialize)]
pub struct RawGrpcInteraction {
    pub request: RawGrpcRequest,
    pub response: RawGrpcResponse,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        serialize_with = "serialize_yaml_safe_opt"
    )]
    pub json_debug: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recorded_at: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct RawGrpcRequest {
    pub method: String,
    #[serde(default)]
    pub metadata: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub body: RawBody,
}

#[derive(Serialize, Deserialize)]
pub struct RawGrpcResponse {
    pub status_code: u32,
    #[serde(default = "default_ok")]
    pub status_message: String,
    #[serde(default)]
    pub metadata: BTreeMap<String, Vec<String>>,
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
    pub headers: BTreeMap<String, Vec<String>>,
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
///
/// `binaries` is the side table produced by [`extract_binary_scalars`];
/// sentinel strings in bodies and headers are resolved against it.
pub fn from_raw(raw: RawCassette, binaries: &[Vec<u8>]) -> pyo3::PyResult<Cassette> {
    let interactions: Vec<HttpInteraction> = raw
        .interactions
        .into_iter()
        .map(|ri| {
            let request = HttpRequest {
                method: ri.request.method,
                uri: ri.request.uri,
                headers: resolve_headers(ri.request.headers, binaries),
                body: match ri.request.parsed_body {
                    Some(v) => Body::json(v),
                    None => body_from_raw(ri.request.body, binaries),
                },
            };
            let response = HttpResponse {
                status: ri.response.status,
                headers: resolve_headers(ri.response.headers, binaries),
                body: match ri.response.parsed_body {
                    Some(v) => Body::json(v),
                    None => body_from_raw(ri.response.body, binaries),
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
        .map(|ri| grpc_from_raw(ri, binaries))
        .collect();

    let ws_interactions: Vec<WsInteraction> = raw
        .ws_interactions
        .into_iter()
        .map(|ri| ws_from_raw(ri, binaries))
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
                headers: sorted_headers(&i.request.headers),
                body: body_to_raw(&i.request.body),
                parsed_body: None,
            },
            response: RawResponse {
                status: i.response.status,
                headers: sorted_headers(&i.response.headers),
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

    let grpc_interactions = cassette.grpc_interactions.iter().map(grpc_to_raw).collect();

    let ws_interactions = cassette.ws_interactions.iter().map(ws_to_raw).collect();

    RawCassette {
        version: cassette.version,
        interactions,
        grpc_interactions,
        ws_interactions,
    }
}

fn grpc_from_raw(raw: RawGrpcInteraction, binaries: &[Vec<u8>]) -> GrpcInteraction {
    GrpcInteraction {
        request: GrpcRequest {
            method: raw.request.method,
            metadata: raw.request.metadata.into_iter().collect(),
            body: body_from_raw(raw.request.body, binaries),
        },
        response: GrpcResponse {
            status_code: raw.response.status_code,
            status_message: raw.response.status_message,
            metadata: raw.response.metadata.into_iter().collect(),
            body: body_from_raw(raw.response.body, binaries),
        },
        json_debug: raw.json_debug,
        recorded_at: raw.recorded_at.unwrap_or_default(),
    }
}

fn grpc_to_raw(i: &GrpcInteraction) -> RawGrpcInteraction {
    RawGrpcInteraction {
        request: RawGrpcRequest {
            method: i.request.method.clone(),
            metadata: sorted_headers(&i.request.metadata),
            body: body_to_raw(&i.request.body),
        },
        response: RawGrpcResponse {
            status_code: i.response.status_code,
            status_message: i.response.status_message.clone(),
            metadata: sorted_headers(&i.response.metadata),
            body: body_to_raw(&i.response.body),
        },
        json_debug: i.json_debug.clone(),
        recorded_at: if i.recorded_at.is_empty() {
            None
        } else {
            Some(i.recorded_at.clone())
        },
    }
}

fn ws_from_raw(raw: RawWsInteraction, binaries: &[Vec<u8>]) -> WsInteraction {
    let frames = raw
        .frames
        .into_iter()
        .map(|f| WsFrame {
            direction: f.direction,
            frame_type: f.frame_type,
            body: body_from_raw(f.body, binaries),
            offset_ms: f.offset_ms,
        })
        .collect();
    WsInteraction {
        uri: raw.uri,
        headers: raw.headers.into_iter().collect(),
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
        headers: sorted_headers(&i.headers),
        frames,
        recorded_at: if i.recorded_at.is_empty() {
            None
        } else {
            Some(i.recorded_at.clone())
        },
    }
}

fn sorted_headers(headers: &HashMap<String, Vec<String>>) -> BTreeMap<String, Vec<String>> {
    headers
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect()
}

fn resolve_headers(
    headers: BTreeMap<String, Vec<String>>,
    binaries: &[Vec<u8>],
) -> HashMap<String, Vec<String>> {
    if binaries.is_empty() {
        return headers.into_iter().collect();
    }
    headers
        .into_iter()
        .map(|(k, values)| {
            let resolved = values
                .into_iter()
                .map(|v| match sentinel_index(&v).and_then(|i| binaries.get(i)) {
                    Some(bytes) => String::from_utf8_lossy(bytes).into_owned(),
                    None => v,
                })
                .collect();
            (k, resolved)
        })
        .collect()
}

fn body_from_raw(raw: RawBody, binaries: &[Vec<u8>]) -> Body {
    match raw.body_type.as_str() {
        "json" => match raw.content {
            Some(content) => Body::json(content),
            None => Body::none(),
        },
        "text" => {
            if let Some(Value::String(s)) = raw.content {
                match sentinel_index(&s).and_then(|i| binaries.get(i)) {
                    Some(bytes) => Body::binary(bytes.clone()),
                    None => Body::text(s),
                }
            } else {
                Body::none()
            }
        }
        "binary" => {
            if let Some(Value::String(s)) = raw.content {
                match crate::body::hex::decode(&s) {
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
            content: Some(val.clone()),
        },
        BodyContent::Text(s) => RawBody {
            body_type: "text".to_string(),
            content: Some(Value::String(s.clone())),
        },
        BodyContent::Binary(b) => RawBody {
            body_type: "binary".to_string(),
            content: Some(Value::String(crate::body::hex::encode(b))),
        },
        BodyContent::None => RawBody {
            body_type: "none".to_string(),
            content: None,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load_yaml(yaml: &str) -> Cassette {
        let (content, binaries) = extract_binary_scalars(yaml);
        let raw: RawCassette = serde_saphyr::from_str(&content).unwrap();
        from_raw(raw, &binaries).unwrap()
    }

    #[test]
    fn test_binary_body_and_headers_from_vcr() {
        // "ABCD" base64 in body, "application/json" base64 in header
        let yaml = "\
version: 1
interactions:
- request:
    method: GET
    uri: https://example.com
    headers: {}
  response:
    status:
      code: 200
      message: OK
    headers:
      content-type:
      - !!binary |
        YXBwbGljYXRpb24vanNvbg==
    body:
      string: !!binary |
        QUJDRA==
";
        let cassette = load_yaml(yaml);
        let response = &cassette.interactions[0].response;
        assert_eq!(response.headers["content-type"], vec!["application/json"]);
        match &response.body.inner {
            BodyContent::Binary(b) => assert_eq!(b, b"ABCD"),
            other => panic!("expected binary body, got {other:?}"),
        }
    }

    #[test]
    fn test_non_utf8_binary_body() {
        // \x00\x01\xff\xfe -> AAH//g==
        let yaml = "\
interactions:
- request:
    method: GET
    uri: https://example.com
    headers: {}
  response:
    status:
      code: 200
      message: OK
    headers: {}
    body:
      string: !!binary |
        AAH//g==
";
        let cassette = load_yaml(yaml);
        match &cassette.interactions[0].response.body.inner {
            BodyContent::Binary(b) => assert_eq!(b, &vec![0u8, 1, 255, 254]),
            other => panic!("expected binary body, got {other:?}"),
        }
    }

    #[test]
    fn test_bare_mapping_body_is_json() {
        let yaml = "\
interactions:
- request:
    method: POST
    uri: https://example.com
    headers: {}
    body:
      model: llama
      stream: false
  response:
    status:
      code: 200
      message: OK
    headers: {}
";
        let cassette = load_yaml(yaml);
        match &cassette.interactions[0].request.body.inner {
            BodyContent::Json(v) => {
                assert_eq!(v["model"], "llama");
                assert_eq!(v["stream"], false);
            }
            other => panic!("expected json body, got {other:?}"),
        }
        assert_eq!(cassette.version, 1);
    }

    #[test]
    fn test_json_body_with_type_key_not_mistaken_for_cassetter_format() {
        let yaml = "\
interactions:
- request:
    method: POST
    uri: https://example.com
    headers: {}
    body:
      type: function
      name: get_weather
  response:
    status:
      code: 200
      message: OK
    headers: {}
";
        let cassette = load_yaml(yaml);
        match &cassette.interactions[0].request.body.inner {
            BodyContent::Json(v) => {
                assert_eq!(v["type"], "function");
                assert_eq!(v["name"], "get_weather");
            }
            other => panic!("expected json body, got {other:?}"),
        }
    }

    #[test]
    fn test_binary_block_with_blank_lines() {
        // Blank lines are legal inside block scalars; "ABCD" split around one.
        let yaml = "\
interactions:
- request:
    method: GET
    uri: https://example.com
    headers: {}
  response:
    status:
      code: 200
      message: OK
    headers: {}
    body:
      string: !!binary |
        QUJD

        RA==
";
        let cassette = load_yaml(yaml);
        match &cassette.interactions[0].response.body.inner {
            BodyContent::Binary(b) => assert_eq!(b, b"ABCD"),
            other => panic!("expected binary body, got {other:?}"),
        }
    }

    #[test]
    fn test_extract_binary_scalars_leaves_plain_yaml_untouched() {
        let yaml = "body:\n  string: |\n    text mentioning !!binary | in prose\n";
        let (content, binaries) = extract_binary_scalars(yaml);
        assert_eq!(content, yaml.trim_end());
        assert!(binaries.is_empty());
    }

    #[test]
    fn test_round_trip_preserves_newline_only_strings() {
        // serde-saphyr auto-selects block scalars for newline-only strings,
        // which do not round-trip; they must be emitted double-quoted.
        let mut cassette = Cassette {
            version: 1,
            interactions: vec![HttpInteraction {
                request: HttpRequest {
                    method: "GET".to_string(),
                    uri: "https://example.com".to_string(),
                    headers: HashMap::new(),
                    body: Body::none(),
                },
                response: HttpResponse {
                    status: 200,
                    headers: HashMap::new(),
                    body: Body::json(serde_json::json!({
                        "content": [{"text": "\n\n", "type": "text"}],
                        "single": "\n",
                        "spaces": " \n ",
                    })),
                },
                recorded_at: String::new(),
            }],
            played_indices: vec![false],
            grpc_interactions: vec![],
            grpc_played: vec![],
            ws_interactions: vec![],
            ws_played: vec![],
        };
        cassette.played_indices = vec![false];
        let yaml = serde_saphyr::to_string(&to_raw(&cassette)).unwrap();
        let reloaded = load_yaml(&yaml);
        match &reloaded.interactions[0].response.body.inner {
            BodyContent::Json(v) => {
                assert_eq!(v["content"][0]["text"], "\n\n");
                assert_eq!(v["single"], "\n");
                assert_eq!(v["spaces"], " \n ");
            }
            other => panic!("expected json body, got {other:?}"),
        }
    }

    #[test]
    fn test_round_trip_preserves_trailing_newlines() {
        // SSE bodies end with blank lines; chomping must not eat them.
        let mut cassette = Cassette {
            version: 1,
            interactions: vec![HttpInteraction {
                request: HttpRequest {
                    method: "GET".to_string(),
                    uri: "https://example.com".to_string(),
                    headers: HashMap::new(),
                    body: Body::none(),
                },
                response: HttpResponse {
                    status: 200,
                    headers: HashMap::new(),
                    body: Body::text("data: x\n\ndata: [DONE]\n\n".to_string()),
                },
                recorded_at: String::new(),
            }],
            played_indices: vec![false],
            grpc_interactions: vec![],
            grpc_played: vec![],
            ws_interactions: vec![],
            ws_played: vec![],
        };
        cassette.played_indices = vec![false];
        let yaml = serde_saphyr::to_string(&to_raw(&cassette)).unwrap();
        let reloaded = load_yaml(&yaml);
        match &reloaded.interactions[0].response.body.inner {
            BodyContent::Text(s) => assert_eq!(s, "data: x\n\ndata: [DONE]\n\n"),
            other => panic!("expected text body, got {other:?}"),
        }
    }
}
