use pyo3::prelude::*;

#[pyclass(skip_from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug)]
pub struct MatchConfig {
    pub match_on: Vec<String>,
    #[pyo3(get, set)]
    pub ignore_json_paths: Vec<String>,
}

const KNOWN_MATCHERS: &[&str] = &["method", "uri", "headers", "body", "json_body"];

fn validate_matchers(match_on: &[String]) -> PyResult<()> {
    if match_on.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "match_on must name at least one matcher (available: {})",
            KNOWN_MATCHERS.join(", ")
        )));
    }
    for name in match_on {
        if !KNOWN_MATCHERS.contains(&name.as_str()) {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown matcher: {name:?} (available: {})",
                KNOWN_MATCHERS.join(", ")
            )));
        }
    }
    Ok(())
}

#[pymethods]
impl MatchConfig {
    #[new]
    #[pyo3(signature = (match_on=None, ignore_json_paths=None))]
    fn new(
        match_on: Option<Vec<String>>,
        ignore_json_paths: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let match_on = match_on.unwrap_or_else(|| vec!["method".to_string(), "uri".to_string()]);
        validate_matchers(&match_on)?;
        Ok(MatchConfig {
            match_on,
            ignore_json_paths: ignore_json_paths.unwrap_or_default(),
        })
    }

    #[getter]
    fn match_on(&self) -> Vec<String> {
        self.match_on.clone()
    }

    /// Validate on assignment too: an unvalidated matcher name would make
    /// `matches_all` reject every request, and before it failed closed it
    /// served an arbitrary recorded response to any request at all.
    #[setter]
    fn set_match_on(&mut self, match_on: Vec<String>) -> PyResult<()> {
        validate_matchers(&match_on)?;
        self.match_on = match_on;
        Ok(())
    }

    fn __repr__(&self) -> String {
        format!(
            "MatchConfig(match_on={:?}, ignore_json_paths={:?})",
            self.match_on, self.ignore_json_paths
        )
    }
}

impl MatchConfig {
    /// Whether the method+URI index can narrow candidates for this config.
    pub fn uses_method_uri_index(&self) -> bool {
        self.match_on.iter().any(|f| f == "method") && self.match_on.iter().any(|f| f == "uri")
    }
}
