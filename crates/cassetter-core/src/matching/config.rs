use crate::{CassetteError, Result};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MatchConfig {
    pub match_on: Vec<String>,
    pub ignore_json_paths: Vec<String>,
}

pub const KNOWN_MATCHERS: &[&str] = &["method", "uri", "headers", "body", "json_body"];

/// Fields matched on when the caller does not name any.
pub const DEFAULT_MATCH_ON: &[&str] = &["method", "uri"];

pub fn validate_matchers(match_on: &[String]) -> Result<()> {
    if match_on.is_empty() {
        return Err(CassetteError::Value(format!(
            "match_on must name at least one matcher (available: {})",
            KNOWN_MATCHERS.join(", ")
        )));
    }
    for name in match_on {
        if !KNOWN_MATCHERS.contains(&name.as_str()) {
            return Err(CassetteError::Value(format!(
                "unknown matcher: {name:?} (available: {})",
                KNOWN_MATCHERS.join(", ")
            )));
        }
    }
    Ok(())
}

impl MatchConfig {
    pub fn new(
        match_on: Option<Vec<String>>,
        ignore_json_paths: Option<Vec<String>>,
    ) -> Result<Self> {
        let match_on =
            match_on.unwrap_or_else(|| DEFAULT_MATCH_ON.iter().map(|s| s.to_string()).collect());
        validate_matchers(&match_on)?;
        Ok(MatchConfig {
            match_on,
            ignore_json_paths: ignore_json_paths.unwrap_or_default(),
        })
    }

    /// Validate on assignment too: an unvalidated matcher name would make
    /// `matches_all` reject every request, and before it failed closed it
    /// served an arbitrary recorded response to any request at all.
    pub fn set_match_on(&mut self, match_on: Vec<String>) -> Result<()> {
        validate_matchers(&match_on)?;
        self.match_on = match_on;
        Ok(())
    }

    /// Whether the method+URI index can narrow candidates for this config.
    pub fn uses_method_uri_index(&self) -> bool {
        self.match_on.iter().any(|f| f == "method") && self.match_on.iter().any(|f| f == "uri")
    }

    pub fn describe(&self) -> String {
        format!(
            "MatchConfig(match_on={:?}, ignore_json_paths={:?})",
            self.match_on, self.ignore_json_paths
        )
    }
}

impl Default for MatchConfig {
    fn default() -> Self {
        MatchConfig::new(None, None).expect("default matchers are valid")
    }
}
