use pyo3::prelude::*;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct MatchConfig {
    #[pyo3(get, set)]
    pub match_on: Vec<String>,
    #[pyo3(get, set)]
    pub ignore_json_paths: Vec<String>,
}

#[pymethods]
impl MatchConfig {
    #[new]
    #[pyo3(signature = (match_on=None, ignore_json_paths=None))]
    fn new(match_on: Option<Vec<String>>, ignore_json_paths: Option<Vec<String>>) -> Self {
        MatchConfig {
            match_on: match_on.unwrap_or_else(|| vec!["method".to_string(), "uri".to_string()]),
            ignore_json_paths: ignore_json_paths.unwrap_or_default(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "MatchConfig(match_on={:?}, ignore_json_paths={:?})",
            self.match_on, self.ignore_json_paths
        )
    }
}
