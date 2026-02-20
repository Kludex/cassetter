pub mod format;
pub mod index;

use std::path::Path;

use pyo3::prelude::*;

use crate::protocol::http::HttpInteraction;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Cassette {
    #[pyo3(get, set)]
    pub version: u32,
    pub interactions: Vec<HttpInteraction>,
    /// Tracks which interactions have been played back (by index).
    pub played_indices: Vec<bool>,
}

#[pymethods]
impl Cassette {
    #[new]
    fn new() -> Self {
        Cassette {
            version: 1,
            interactions: Vec::new(),
            played_indices: Vec::new(),
        }
    }

    #[getter]
    fn interactions(&self) -> Vec<HttpInteraction> {
        self.interactions.clone()
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
        let raw: format::RawCassette = serde_yaml::from_str(&content).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("YAML parse error: {e}"))
        })?;
        format::from_raw(raw)
    }

    fn save(&self, path: &str) -> PyResult<()> {
        let raw = format::to_raw(self);
        let yaml = serde_yaml::to_string(&raw).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("YAML serialize error: {e}"))
        })?;
        // Ensure parent directory exists
        let p = Path::new(path);
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                pyo3::exceptions::PyIOError::new_err(format!("mkdir error: {e}"))
            })?;
        }
        std::fs::write(p, yaml).map_err(|e| {
            pyo3::exceptions::PyIOError::new_err(format!("write error: {e}"))
        })?;
        Ok(())
    }

    fn __len__(&self) -> usize {
        self.interactions.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "Cassette(version={}, interactions={})",
            self.version,
            self.interactions.len()
        )
    }
}
