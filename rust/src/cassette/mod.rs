pub mod format;
pub mod format_toml;
pub mod index;
pub mod ordering;

use std::path::Path;

use pyo3::prelude::*;

use crate::matching::config::MatchConfig;
use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::{HttpInteraction, HttpRequest};
use crate::protocol::ws::WsInteraction;

#[pyclass(skip_from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Default)]
pub struct Cassette {
    #[pyo3(get, set)]
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

#[pymethods]
impl Cassette {
    #[new]
    fn new() -> Self {
        Cassette {
            version: 1,
            ..Cassette::default()
        }
    }

    #[getter]
    fn interactions(&self) -> Vec<HttpInteraction> {
        self.interactions.clone()
    }

    /// Find a matching interaction and mark it played, in one step.
    ///
    /// Matching against the interactions already held here avoids marshalling
    /// the whole cassette across the FFI boundary on every request, and makes
    /// find-then-mark atomic so two threads cannot consume the same
    /// interaction.
    fn take_match(
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

    /// Find a matching gRPC interaction and mark it played, in one step.
    fn take_grpc_match(&mut self, method: &str) -> Option<(usize, GrpcInteraction)> {
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

    /// Find a matching WebSocket interaction and mark it played, in one step.
    fn take_ws_match(&mut self, uri: &str) -> Option<(usize, WsInteraction)> {
        let idx =
            crate::matching::find_ws_match_index(uri, &self.ws_interactions, &self.ws_played)?;
        if let Some(played) = self.ws_played.get_mut(idx) {
            *played = true;
        }
        Some((idx, self.ws_interactions[idx].clone()))
    }

    #[getter]
    fn played_indices(&self) -> Vec<bool> {
        self.played_indices.clone()
    }

    #[setter]
    fn set_interactions(&mut self, interactions: Vec<HttpInteraction>) {
        self.played_indices = vec![false; interactions.len()];
        self.interactions = interactions;
        self.index = None;
    }

    fn add_interaction(&mut self, interaction: HttpInteraction) {
        self.interactions.push(interaction);
        self.played_indices.push(false);
        self.index = None;
    }

    fn mark_played(&mut self, index: usize) -> PyResult<()> {
        if index >= self.played_indices.len() {
            return Err(pyo3::exceptions::PyIndexError::new_err(
                "interaction index out of range",
            ));
        }
        self.played_indices[index] = true;
        Ok(())
    }

    #[getter]
    fn unplayed_count(&self) -> usize {
        self.played_indices.iter().filter(|&&p| !p).count()
    }

    // --- gRPC ---

    #[getter]
    fn grpc_interactions(&self) -> Vec<GrpcInteraction> {
        self.grpc_interactions.clone()
    }

    #[getter]
    fn grpc_played(&self) -> Vec<bool> {
        self.grpc_played.clone()
    }

    #[setter]
    fn set_grpc_interactions(&mut self, interactions: Vec<GrpcInteraction>) {
        self.grpc_played = vec![false; interactions.len()];
        self.grpc_interactions = interactions;
    }

    fn add_grpc_interaction(&mut self, interaction: GrpcInteraction) {
        self.grpc_interactions.push(interaction);
        self.grpc_played.push(false);
    }

    fn mark_grpc_played(&mut self, index: usize) -> PyResult<()> {
        if index >= self.grpc_played.len() {
            return Err(pyo3::exceptions::PyIndexError::new_err(
                "gRPC interaction index out of range",
            ));
        }
        self.grpc_played[index] = true;
        Ok(())
    }

    // --- WebSocket ---

    #[getter]
    fn ws_interactions(&self) -> Vec<WsInteraction> {
        self.ws_interactions.clone()
    }

    #[getter]
    fn ws_played(&self) -> Vec<bool> {
        self.ws_played.clone()
    }

    #[setter]
    fn set_ws_interactions(&mut self, interactions: Vec<WsInteraction>) {
        self.ws_played = vec![false; interactions.len()];
        self.ws_interactions = interactions;
    }

    fn add_ws_interaction(&mut self, interaction: WsInteraction) {
        self.ws_interactions.push(interaction);
        self.ws_played.push(false);
    }

    fn mark_ws_played(&mut self, index: usize) -> PyResult<()> {
        if index >= self.ws_played.len() {
            return Err(pyo3::exceptions::PyIndexError::new_err(
                "WebSocket interaction index out of range",
            ));
        }
        self.ws_played[index] = true;
        Ok(())
    }

    /// Load a cassette from disk.
    ///
    /// The GIL is released for the whole parse: a multi-megabyte cassette
    /// would otherwise freeze every other thread in the interpreter.
    #[staticmethod]
    fn load(py: Python<'_>, path: &str) -> PyResult<Cassette> {
        py.detach(|| Cassette::load_impl(path))
    }

    /// The order these interactions should be written in.
    ///
    /// `sort_config` puts them in a canonical order instead of the order their
    /// responses arrived in; `record_order` breaks ties between interactions
    /// the matcher cannot tell apart. See [`ordering`].
    ///
    /// Separate from `save` so the order can be taken from whichever cassette
    /// the matcher actually compares - with a `uri_normalizer` that is the
    /// normalized mirror, not the interactions written to disk.
    #[pyo3(signature = (sort_config=None, record_order=None))]
    fn output_order(
        &self,
        sort_config: Option<&MatchConfig>,
        record_order: Option<Vec<usize>>,
    ) -> Vec<usize> {
        ordering::output_order(
            &self.interactions,
            sort_config,
            record_order.as_deref().unwrap_or(&[]),
        )
    }

    /// Save the cassette to disk, releasing the GIL for serialization and I/O.
    #[pyo3(signature = (path, order=None))]
    fn save(&self, py: Python<'_>, path: &str, order: Option<Vec<usize>>) -> PyResult<()> {
        let order = match order {
            Some(order) => {
                ordering::validate(&order, self.interactions.len())
                    .map_err(pyo3::exceptions::PyValueError::new_err)?;
                order
            }
            None => (0..self.interactions.len()).collect(),
        };
        py.detach(|| self.save_impl(path, &order))
    }

    fn __len__(&self) -> usize {
        self.interactions.len() + self.grpc_interactions.len() + self.ws_interactions.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "Cassette(version={}, http={}, grpc={}, ws={})",
            self.version,
            self.interactions.len(),
            self.grpc_interactions.len(),
            self.ws_interactions.len(),
        )
    }
}

impl Cassette {
    fn load_impl(path: &str) -> PyResult<Cassette> {
        let p = Path::new(path);
        if !p.exists() {
            return Err(pyo3::exceptions::PyFileNotFoundError::new_err(format!(
                "cassette not found: {path}"
            )));
        }
        let content = std::fs::read_to_string(p)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("read error: {e}")))?;

        if is_toml(path) {
            let raw: format_toml::TomlCassette = toml::from_str(&content).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("TOML parse error: {e}"))
            })?;
            return Ok(format_toml::from_toml(raw));
        }

        let (content, binaries) = format::extract_binary_scalars(&content);
        // strict_booleans: YAML 1.2 core schema semantics - only true/false are
        // booleans, so unquoted yes/no/on/off scalars stay strings, matching
        // how existing cassettes were written.
        let options = serde_saphyr::options! { strict_booleans: true };
        let raw: format::RawCassette = serde_saphyr::from_str_with_options(&content, options)
            .map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("YAML parse error: {e}"))
            })?;
        format::from_raw(raw, &binaries)
    }

    fn save_impl(&self, path: &str, order: &[usize]) -> PyResult<()> {
        // Ensure parent directory exists
        let p = Path::new(path);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("mkdir error: {e}")))?;
        }

        let out = if is_toml(path) {
            if !self.grpc_interactions.is_empty() || !self.ws_interactions.is_empty() {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "TOML cassettes cannot store gRPC or WebSocket interactions; use YAML",
                ));
            }
            let raw = format_toml::to_toml(self, order);
            toml::to_string_pretty(&raw).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("TOML serialize error: {e}"))
            })?
        } else {
            let raw = format::to_raw(self, order);
            serde_saphyr::to_string(&raw).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("YAML serialize error: {e}"))
            })?
        };
        // Write via a temp file + rename so a crash mid-write never leaves a
        // truncated cassette.
        let tmp = p.with_extension(match p.extension().and_then(|e| e.to_str()) {
            Some(ext) => format!("tmp.{ext}"),
            None => "tmp".to_string(),
        });
        std::fs::write(&tmp, out)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("write error: {e}")))?;
        // Preserve the original file's permissions across the rename: the temp
        // file is created with the process umask, which would drop a
        // restrictive mode (e.g. 0600 on a cassette holding unscrubbed data).
        #[cfg(unix)]
        if let Ok(meta) = std::fs::metadata(p) {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(
                &tmp,
                std::fs::Permissions::from_mode(meta.permissions().mode()),
            );
        }
        std::fs::rename(&tmp, p)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("rename error: {e}")))?;
        Ok(())
    }
}

fn is_toml(path: &str) -> bool {
    Path::new(path)
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("toml"))
}
