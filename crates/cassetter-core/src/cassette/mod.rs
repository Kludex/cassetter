pub mod format;
pub mod format_toml;
pub mod index;
pub mod ordering;

use std::path::Path;

use crate::matching::config::MatchConfig;
use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::{HttpInteraction, HttpRequest};
use crate::protocol::ws::WsInteraction;
use crate::{CassetteError, Result};

/// Current cassette file format version.
pub const FORMAT_VERSION: u32 = 1;

#[derive(Clone, Debug, Default)]
pub struct Cassette {
    pub version: u32,
    pub interactions: Vec<HttpInteraction>,
    pub played_indices: Vec<bool>,
    pub grpc_interactions: Vec<GrpcInteraction>,
    pub grpc_played: Vec<bool>,
    pub ws_interactions: Vec<WsInteraction>,
    pub ws_played: Vec<bool>,
    /// Cached method+URI index, invalidated whenever `interactions` changes.
    index: Option<index::CassetteIndex>,
}

impl Cassette {
    /// Start an empty cassette.
    pub fn new() -> Self {
        Cassette {
            version: FORMAT_VERSION,
            ..Cassette::default()
        }
    }

    // --- HTTP ---

    /// Replace the HTTP interactions, resetting played state.
    pub fn set_interactions(&mut self, interactions: Vec<HttpInteraction>) {
        self.played_indices = vec![false; interactions.len()];
        self.interactions = interactions;
        self.index = None;
    }

    /// Append an HTTP interaction, unplayed.
    pub fn add_interaction(&mut self, interaction: HttpInteraction) {
        self.interactions.push(interaction);
        self.played_indices.push(false);
        self.index = None;
    }

    /// Mark an HTTP interaction played.
    pub fn mark_played(&mut self, index: usize) -> Result<()> {
        if index >= self.played_indices.len() {
            return Err(CassetteError::IndexOutOfRange(
                "interaction index out of range".to_string(),
            ));
        }
        self.played_indices[index] = true;
        Ok(())
    }

    /// How many HTTP interactions have not been played.
    pub fn unplayed_count(&self) -> usize {
        self.played_indices.iter().filter(|&&p| !p).count()
    }

    /// Find a matching interaction and mark it played, in one step.
    ///
    /// Matching against the interactions already held here avoids marshalling
    /// the whole cassette across a binding boundary on every request, and
    /// makes find-then-mark atomic so two threads cannot consume the same
    /// interaction.
    pub fn take_match(
        &mut self,
        request: &HttpRequest,
        config: &MatchConfig,
    ) -> Option<(usize, HttpInteraction)> {
        if config.uses_method_uri_index() && self.index.is_none() {
            self.index = Some(index::CassetteIndex::build(&self.interactions));
        }
        let idx = crate::matching::find_match_index(
            request,
            &self.interactions,
            &self.played_indices,
            config,
            config
                .uses_method_uri_index()
                .then_some(self.index.as_ref())
                .flatten(),
        )?;
        if let Some(played) = self.played_indices.get_mut(idx) {
            *played = true;
        }
        Some((idx, self.interactions[idx].clone()))
    }

    // --- gRPC ---

    /// Replace the gRPC interactions, resetting played state.
    pub fn set_grpc_interactions(&mut self, interactions: Vec<GrpcInteraction>) {
        self.grpc_played = vec![false; interactions.len()];
        self.grpc_interactions = interactions;
    }

    /// Append a gRPC interaction, unplayed.
    pub fn add_grpc_interaction(&mut self, interaction: GrpcInteraction) {
        self.grpc_interactions.push(interaction);
        self.grpc_played.push(false);
    }

    /// Mark a gRPC interaction played.
    pub fn mark_grpc_played(&mut self, index: usize) -> Result<()> {
        if index >= self.grpc_played.len() {
            return Err(CassetteError::IndexOutOfRange(
                "gRPC interaction index out of range".to_string(),
            ));
        }
        self.grpc_played[index] = true;
        Ok(())
    }

    /// Find a matching gRPC interaction and mark it played, in one step.
    pub fn take_grpc_match(&mut self, method: &str) -> Option<(usize, GrpcInteraction)> {
        let idx = crate::matching::find_grpc_match_index(
            method,
            &self.grpc_interactions,
            &self.grpc_played,
        )?;
        if let Some(played) = self.grpc_played.get_mut(idx) {
            *played = true;
        }
        Some((idx, self.grpc_interactions[idx].clone()))
    }

    // --- WebSocket ---

    /// Replace the WebSocket interactions, resetting played state.
    pub fn set_ws_interactions(&mut self, interactions: Vec<WsInteraction>) {
        self.ws_played = vec![false; interactions.len()];
        self.ws_interactions = interactions;
    }

    /// Append a WebSocket interaction, unplayed.
    pub fn add_ws_interaction(&mut self, interaction: WsInteraction) {
        self.ws_interactions.push(interaction);
        self.ws_played.push(false);
    }

    /// Mark a WebSocket interaction played.
    pub fn mark_ws_played(&mut self, index: usize) -> Result<()> {
        if index >= self.ws_played.len() {
            return Err(CassetteError::IndexOutOfRange(
                "WebSocket interaction index out of range".to_string(),
            ));
        }
        self.ws_played[index] = true;
        Ok(())
    }

    /// Find a matching WebSocket interaction and mark it played, in one step.
    pub fn take_ws_match(&mut self, uri: &str) -> Option<(usize, WsInteraction)> {
        let idx =
            crate::matching::find_ws_match_index(uri, &self.ws_interactions, &self.ws_played)?;
        if let Some(played) = self.ws_played.get_mut(idx) {
            *played = true;
        }
        Some((idx, self.ws_interactions[idx].clone()))
    }

    // --- Ordering ---

    /// The order these interactions should be written in.
    ///
    /// `sort_config` puts them in a canonical order instead of the order their
    /// responses arrived in; `record_order` breaks ties between interactions
    /// the matcher cannot tell apart. See [`ordering`].
    ///
    /// Separate from `save` so the order can be taken from whichever cassette
    /// the matcher actually compares - with a `uri_normalizer` that is the
    /// normalized mirror, not the interactions written to disk.
    pub fn output_order(
        &self,
        sort_config: Option<&MatchConfig>,
        record_order: Option<&[usize]>,
    ) -> Vec<usize> {
        ordering::output_order(&self.interactions, sort_config, record_order.unwrap_or(&[]))
    }

    // --- Persistence ---

    /// Parse a cassette from YAML text.
    pub fn from_yaml(content: &str) -> Result<Cassette> {
        let (content, binaries) = format::extract_binary_scalars(content);
        // strict_booleans: YAML 1.2 core schema semantics - only true/false are
        // booleans, so unquoted yes/no/on/off scalars stay strings, matching
        // how existing cassettes were written.
        let options = serde_saphyr::options! { strict_booleans: true };
        let raw: format::RawCassette = serde_saphyr::from_str_with_options(&content, options)
            .map_err(|e| CassetteError::Format(format!("YAML parse error: {e}")))?;
        format::from_raw(raw, &binaries)
    }

    /// Parse a cassette from TOML text.
    pub fn from_toml(content: &str) -> Result<Cassette> {
        let raw: format_toml::TomlCassette = toml::from_str(content)
            .map_err(|e| CassetteError::Format(format!("TOML parse error: {e}")))?;
        format_toml::from_toml(raw)
    }

    /// Serialize to YAML text.
    pub fn to_yaml(&self, order: &[usize]) -> Result<String> {
        let raw = format::to_raw(self, order);
        serde_saphyr::to_string(&raw)
            .map_err(|e| CassetteError::Format(format!("YAML serialize error: {e}")))
    }

    /// Serialize to TOML text. TOML cannot carry gRPC or WebSocket interactions.
    pub fn to_toml(&self, order: &[usize]) -> Result<String> {
        if !self.grpc_interactions.is_empty() || !self.ws_interactions.is_empty() {
            return Err(CassetteError::Value(
                "TOML cassettes cannot store gRPC or WebSocket interactions; use YAML".to_string(),
            ));
        }
        let raw = format_toml::to_toml(self, order);
        toml::to_string_pretty(&raw)
            .map_err(|e| CassetteError::Format(format!("TOML serialize error: {e}")))
    }

    /// Load a cassette from disk, picking the format from the file extension.
    pub fn load(path: &str) -> Result<Cassette> {
        let p = Path::new(path);
        if !p.exists() {
            return Err(CassetteError::NotFound(format!(
                "cassette not found: {path}"
            )));
        }
        let content = std::fs::read_to_string(p)
            .map_err(|e| CassetteError::Io(format!("read error: {e}")))?;

        if is_toml(path) {
            Cassette::from_toml(&content)
        } else {
            Cassette::from_yaml(&content)
        }
    }

    /// Save the cassette to disk.
    ///
    /// `order` is the write order (see [`Cassette::output_order`]); pass `None`
    /// to keep the recorded order. `mode` carries a file mode to apply for a
    /// caller that already removed the original.
    pub fn save(&self, path: &str, order: Option<&[usize]>, mode: Option<u32>) -> Result<()> {
        let owned;
        let order = match order {
            Some(order) => {
                ordering::validate(order, self.interactions.len()).map_err(CassetteError::Value)?;
                order
            }
            None => {
                owned = (0..self.interactions.len()).collect::<Vec<_>>();
                &owned
            }
        };

        // Ensure parent directory exists
        let p = Path::new(path);
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)
                    .map_err(|e| CassetteError::Io(format!("mkdir error: {e}")))?;
            }
        }

        let out = if is_toml(path) {
            self.to_toml(order)?
        } else {
            self.to_yaml(order)?
        };

        // Write via a temp file + rename so a crash mid-write never leaves a
        // truncated cassette.
        let tmp = p.with_extension(match p.extension().and_then(|e| e.to_str()) {
            Some(ext) => format!("tmp.{ext}"),
            None => "tmp".to_string(),
        });
        std::fs::write(&tmp, out).map_err(|e| CassetteError::Io(format!("write error: {e}")))?;
        // Preserve the original file's permissions across the rename: the temp
        // file is created with the process umask, which would drop a
        // restrictive mode (e.g. 0600 on a cassette holding unscrubbed data).
        // `mode` carries it for a caller that already removed the original -
        // setting it after the rename would publish the file at the umask first.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let preserved = mode.or_else(|| {
                std::fs::metadata(p)
                    .ok()
                    .map(|meta| meta.permissions().mode())
            });
            if let Some(preserved) = preserved {
                let _ = std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(preserved));
            }
        }
        #[cfg(not(unix))]
        let _ = mode;
        std::fs::rename(&tmp, p).map_err(|e| CassetteError::Io(format!("rename error: {e}")))?;
        Ok(())
    }

    /// How many interactions this holds, across all protocols.
    pub fn len(&self) -> usize {
        self.interactions.len() + self.grpc_interactions.len() + self.ws_interactions.len()
    }

    /// Whether it holds no interactions at all.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// A short, readable rendering for a binding to surface.
    pub fn describe(&self) -> String {
        format!(
            "Cassette(version={}, http={}, grpc={}, ws={})",
            self.version,
            self.interactions.len(),
            self.grpc_interactions.len(),
            self.ws_interactions.len(),
        )
    }
}

/// Whether this path names a TOML cassette rather than a YAML one.
pub fn is_toml(path: &str) -> bool {
    Path::new(path)
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("toml"))
}
