//! napi-rs bindings for `cassetter-core`.
//!
//! Structured values cross the boundary as plain JS objects shaped exactly
//! like the cassette file format (see `cassetter_core::interop`), so the Node
//! binding, the Python binding, and the YAML/TOML on disk all agree on one
//! representation.

use cassetter_core as core;
use core::CassetteError;
use napi::bindgen_prelude::*;
use napi_derive::napi;
use serde_json::{json, Value};

fn to_napi_err(e: CassetteError) -> Error {
    let status = match e {
        CassetteError::IndexOutOfRange(_) | CassetteError::Value(_) => Status::InvalidArg,
        _ => Status::GenericFailure,
    };
    Error::new(status, e.to_string())
}

fn to_array(values: impl IntoIterator<Item = Value>) -> Value {
    Value::Array(values.into_iter().collect())
}

#[napi(js_name = "Cassette")]
pub struct JsCassette {
    inner: core::cassette::Cassette,
}

#[napi]
impl JsCassette {
    #[napi(constructor)]
    pub fn new() -> Self {
        JsCassette {
            inner: core::cassette::Cassette::new(),
        }
    }

    /// Load a cassette from disk. The format follows the file extension:
    /// `.toml` for TOML, anything else for YAML.
    #[napi(factory)]
    pub fn load(path: String) -> Result<Self> {
        core::cassette::Cassette::load(&path)
            .map(|inner| JsCassette { inner })
            .map_err(to_napi_err)
    }

    #[napi(factory)]
    pub fn from_yaml(content: String) -> Result<Self> {
        core::cassette::Cassette::from_yaml(&content)
            .map(|inner| JsCassette { inner })
            .map_err(to_napi_err)
    }

    #[napi(factory)]
    pub fn from_toml(content: String) -> Result<Self> {
        core::cassette::Cassette::from_toml(&content)
            .map(|inner| JsCassette { inner })
            .map_err(to_napi_err)
    }

    /// Write the cassette to disk. `order` is an optional write order from
    /// `outputOrder`; `mode` a file mode to apply for a caller that already
    /// removed the original.
    #[napi]
    pub fn save(&self, path: String, order: Option<Vec<u32>>, mode: Option<u32>) -> Result<()> {
        let order: Option<Vec<usize>> = order.map(|o| o.into_iter().map(|i| i as usize).collect());
        self.inner
            .save(&path, order.as_deref(), mode)
            .map_err(to_napi_err)
    }

    #[napi]
    pub fn to_yaml(&self, order: Option<Vec<u32>>) -> Result<String> {
        let order = self.resolve_order(order);
        self.inner.to_yaml(&order).map_err(to_napi_err)
    }

    #[napi]
    pub fn to_toml(&self, order: Option<Vec<u32>>) -> Result<String> {
        let order = self.resolve_order(order);
        self.inner.to_toml(&order).map_err(to_napi_err)
    }

    /// The order these interactions should be written in.
    #[napi]
    pub fn output_order(
        &self,
        sort_config: Option<Value>,
        record_order: Option<Vec<u32>>,
    ) -> Result<Vec<u32>> {
        let config = match sort_config {
            Some(v) => Some(core::interop::match_config_from_json(&v).map_err(to_napi_err)?),
            None => None,
        };
        let record: Option<Vec<usize>> =
            record_order.map(|o| o.into_iter().map(|i| i as usize).collect());
        Ok(self
            .inner
            .output_order(config.as_ref(), record.as_deref())
            .into_iter()
            .map(|i| i as u32)
            .collect())
    }

    #[napi(getter)]
    pub fn version(&self) -> u32 {
        self.inner.version
    }

    #[napi(getter)]
    pub fn length(&self) -> u32 {
        self.inner.len() as u32
    }

    // --- HTTP ---

    #[napi(getter)]
    pub fn interactions(&self) -> Value {
        to_array(
            self.inner
                .interactions
                .iter()
                .map(core::interop::interaction_to_json),
        )
    }

    #[napi(getter)]
    pub fn played_indices(&self) -> Vec<bool> {
        self.inner.played_indices.clone()
    }

    #[napi(getter)]
    pub fn unplayed_count(&self) -> u32 {
        self.inner.unplayed_count() as u32
    }

    #[napi]
    pub fn add_interaction(&mut self, interaction: Value) {
        self.inner
            .add_interaction(core::interop::interaction_from_json(&interaction));
    }

    #[napi]
    pub fn mark_played(&mut self, index: u32) -> Result<()> {
        self.inner.mark_played(index as usize).map_err(to_napi_err)
    }

    /// Find an interaction matching `request` and mark it played, in one step.
    /// Returns `{index, interaction}` or `null`.
    ///
    /// Matching happens against the interactions already held in Rust, so the
    /// list never crosses the FFI boundary.
    #[napi]
    pub fn take_match(&mut self, request: Value, config: Option<Value>) -> Result<Option<Value>> {
        let req = core::interop::request_from_json(&request);
        let cfg = match config {
            Some(v) => core::interop::match_config_from_json(&v).map_err(to_napi_err)?,
            None => core::matching::config::MatchConfig::default(),
        };
        Ok(self.inner.take_match(&req, &cfg).map(|(index, i)| {
            json!({
                "index": index,
                "interaction": core::interop::interaction_to_json(&i),
            })
        }))
    }

    // --- gRPC ---

    #[napi(getter)]
    pub fn grpc_interactions(&self) -> Value {
        to_array(
            self.inner
                .grpc_interactions
                .iter()
                .map(core::interop::grpc_interaction_to_json),
        )
    }

    #[napi(getter)]
    pub fn grpc_played(&self) -> Vec<bool> {
        self.inner.grpc_played.clone()
    }

    #[napi]
    pub fn add_grpc_interaction(&mut self, interaction: Value) {
        self.inner
            .add_grpc_interaction(core::interop::grpc_interaction_from_json(&interaction));
    }

    #[napi]
    pub fn mark_grpc_played(&mut self, index: u32) -> Result<()> {
        self.inner
            .mark_grpc_played(index as usize)
            .map_err(to_napi_err)
    }

    #[napi]
    pub fn take_grpc_match(&mut self, method: String) -> Option<Value> {
        self.inner.take_grpc_match(&method).map(|(index, i)| {
            json!({
                "index": index,
                "interaction": core::interop::grpc_interaction_to_json(&i),
            })
        })
    }

    // --- WebSocket ---

    #[napi(getter)]
    pub fn ws_interactions(&self) -> Value {
        to_array(
            self.inner
                .ws_interactions
                .iter()
                .map(core::interop::ws_interaction_to_json),
        )
    }

    #[napi(getter)]
    pub fn ws_played(&self) -> Vec<bool> {
        self.inner.ws_played.clone()
    }

    #[napi]
    pub fn add_ws_interaction(&mut self, interaction: Value) {
        self.inner
            .add_ws_interaction(core::interop::ws_interaction_from_json(&interaction));
    }

    #[napi]
    pub fn mark_ws_played(&mut self, index: u32) -> Result<()> {
        self.inner
            .mark_ws_played(index as usize)
            .map_err(to_napi_err)
    }

    #[napi]
    pub fn take_ws_match(&mut self, uri: String) -> Option<Value> {
        self.inner.take_ws_match(&uri).map(|(index, i)| {
            json!({
                "index": index,
                "interaction": core::interop::ws_interaction_to_json(&i),
            })
        })
    }
}

impl JsCassette {
    fn resolve_order(&self, order: Option<Vec<u32>>) -> Vec<usize> {
        match order {
            Some(o) => o.into_iter().map(|i| i as usize).collect(),
            None => (0..self.inner.interactions.len()).collect(),
        }
    }
}

impl Default for JsCassette {
    fn default() -> Self {
        Self::new()
    }
}

// --- Free functions ---

/// Decompress, decode, and classify a raw body into `{type, content}`.
#[napi]
pub fn process_body(
    raw_bytes: Buffer,
    content_type: Option<String>,
    content_encoding: Option<String>,
    max_decompressed: Option<u32>,
) -> Result<Value> {
    core::body::process_body(
        raw_bytes.to_vec(),
        content_type.as_deref(),
        content_encoding.as_deref(),
        max_decompressed
            .map(|m| m as usize)
            .unwrap_or(core::body::compression::DEFAULT_MAX_DECOMPRESSED),
    )
    .map(|b| core::interop::body_to_json(&b))
    .map_err(to_napi_err)
}

/// Strip sensitive headers, query params, and body fields from an interaction.
#[napi]
pub fn scrub_interaction(interaction: Value, config: Option<Value>) -> Result<Value> {
    let i = core::interop::interaction_from_json(&interaction);
    let cfg = security_config(config)?;
    Ok(core::interop::interaction_to_json(
        &core::security::scrub_interaction(&i, &cfg),
    ))
}

/// Strip sensitive metadata and `jsonDebug` fields from a gRPC interaction.
#[napi]
pub fn scrub_grpc_interaction(interaction: Value, config: Option<Value>) -> Result<Value> {
    let i = core::interop::grpc_interaction_from_json(&interaction);
    let cfg = security_config(config)?;
    Ok(core::interop::grpc_interaction_to_json(
        &core::security::scrub_grpc_interaction(&i, &cfg),
    ))
}

/// Strip sensitive handshake headers and frame-body fields from a WebSocket
/// interaction.
#[napi]
pub fn scrub_ws_interaction(interaction: Value, config: Option<Value>) -> Result<Value> {
    let i = core::interop::ws_interaction_from_json(&interaction);
    let cfg = security_config(config)?;
    Ok(core::interop::ws_interaction_to_json(
        &core::security::scrub_ws_interaction(&i, &cfg),
    ))
}

fn security_config(config: Option<Value>) -> Result<core::security::SecurityConfig> {
    match config {
        Some(v) => core::interop::security_config_from_json(&v).map_err(to_napi_err),
        None => Ok(core::security::SecurityConfig::with_defaults()),
    }
}

// --- Defaults ---
//
// Exposed so bindings never keep their own copies of these lists.

#[napi]
pub fn default_filter_headers() -> Vec<String> {
    core::security::defaults::DEFAULT_FILTER_HEADERS
        .iter()
        .map(|s| s.to_string())
        .collect()
}

#[napi]
pub fn default_filter_query_parameters() -> Vec<String> {
    core::security::defaults::DEFAULT_FILTER_QUERY_PARAMS
        .iter()
        .map(|s| s.to_string())
        .collect()
}

#[napi]
pub fn default_body_scrub_patterns() -> Vec<String> {
    core::security::defaults::DEFAULT_BODY_SCRUB_PATTERNS
        .iter()
        .map(|s| s.to_string())
        .collect()
}

#[napi]
pub fn default_match_on() -> Vec<String> {
    core::matching::config::DEFAULT_MATCH_ON
        .iter()
        .map(|s| s.to_string())
        .collect()
}

#[napi]
pub fn known_matchers() -> Vec<String> {
    core::matching::config::KNOWN_MATCHERS
        .iter()
        .map(|s| s.to_string())
        .collect()
}

#[napi]
pub fn default_replacement() -> String {
    core::security::DEFAULT_REPLACEMENT.to_string()
}

/// Cassette file format version written by this build.
#[napi]
pub fn format_version() -> u32 {
    core::cassette::FORMAT_VERSION
}
