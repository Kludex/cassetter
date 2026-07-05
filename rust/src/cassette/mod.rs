pub mod format;
pub mod format_toml;
pub mod index;

use std::path::Path;

use pyo3::prelude::*;

use crate::protocol::grpc::GrpcInteraction;
use crate::protocol::http::HttpInteraction;
use crate::protocol::ws::WsInteraction;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Cassette {
    #[pyo3(get, set)]
    pub version: u32,
    pub interactions: Vec<HttpInteraction>,
    pub played_indices: Vec<bool>,
    pub grpc_interactions: Vec<GrpcInteraction>,
    pub grpc_played: Vec<bool>,
    pub ws_interactions: Vec<WsInteraction>,
    pub ws_played: Vec<bool>,
}

#[pymethods]
impl Cassette {
    #[new]
    fn new() -> Self {
        Cassette {
            version: 1,
            interactions: Vec::new(),
            played_indices: Vec::new(),
            grpc_interactions: Vec::new(),
            grpc_played: Vec::new(),
            ws_interactions: Vec::new(),
            ws_played: Vec::new(),
        }
    }

    #[getter]
    fn interactions(&self) -> Vec<HttpInteraction> {
        self.interactions.clone()
    }

    #[getter]
    fn played_indices(&self) -> Vec<bool> {
        self.played_indices.clone()
    }

    #[setter]
    fn set_interactions(&mut self, interactions: Vec<HttpInteraction>) {
        self.played_indices = vec![false; interactions.len()];
        self.interactions = interactions;
    }

    fn add_interaction(&mut self, interaction: HttpInteraction) {
        self.interactions.push(interaction);
        self.played_indices.push(false);
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

    #[staticmethod]
    fn load(path: &str) -> PyResult<Cassette> {
        let p = Path::new(path);
        if !p.exists() {
            return Err(pyo3::exceptions::PyFileNotFoundError::new_err(format!(
                "cassette not found: {path}"
            )));
        }
        let content = std::fs::read_to_string(p).map_err(|e| {
            pyo3::exceptions::PyIOError::new_err(format!("read error: {e}"))
        })?;

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

    fn save(&self, path: &str) -> PyResult<()> {
        // Ensure parent directory exists
        let p = Path::new(path);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                pyo3::exceptions::PyIOError::new_err(format!("mkdir error: {e}"))
            })?;
        }

        if is_toml(path) {
            let raw = format_toml::to_toml(self);
            let out = toml::to_string_pretty(&raw).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("TOML serialize error: {e}"))
            })?;
            std::fs::write(p, out).map_err(|e| {
                pyo3::exceptions::PyIOError::new_err(format!("write error: {e}"))
            })?;
        } else {
            let raw = format::to_raw(self);
            let yaml = serde_saphyr::to_string(&raw).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("YAML serialize error: {e}"))
            })?;
            std::fs::write(p, yaml).map_err(|e| {
                pyo3::exceptions::PyIOError::new_err(format!("write error: {e}"))
            })?;
        }
        Ok(())
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

fn is_toml(path: &str) -> bool {
    Path::new(path)
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("toml"))
}
