use pyo3::prelude::*;

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct MatchConfig {
    #[pyo3(get, set)]
    pub match_on: Vec<String>,
    #[pyo3(get, set)]
    pub ignore_json_paths: Vec<String>,
}

const KNOWN_MATCHERS: &[&str] = &["method", "uri", "headers", "body", "json_body"];

#[pymethods]
impl MatchConfig {
    #[new]
    #[pyo3(signature = (match_on=None, ignore_json_paths=None))]
    fn new(
        match_on: Option<Vec<String>>,
        ignore_json_paths: Option<Vec<String>>,
    ) -> pyo3::PyResult<Self> {
        let match_on = match_on.unwrap_or_else(|| vec!["method".to_string(), "uri".to_string()]);
        for name in &match_on {
            if !KNOWN_MATCHERS.contains(&name.as_str()) {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown matcher: {name:?} (available: {})",
                    KNOWN_MATCHERS.join(", ")
                )));
            }
        }
        Ok(MatchConfig {
            match_on,
            ignore_json_paths: ignore_json_paths.unwrap_or_default(),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "MatchConfig(match_on={:?}, ignore_json_paths={:?})",
            self.match_on, self.ignore_json_paths
        )
    }
}
