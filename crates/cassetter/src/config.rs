use std::path::{Path, PathBuf};

use cassetter_core::matching::config::MatchConfig;
pub use cassetter_core::recording::RecordMode;
use cassetter_core::security::SecurityConfig;

use crate::{Error, Recorder, Result};

/// Configures a [`Recorder`].
#[derive(Debug)]
pub struct RecorderBuilder {
    pub(crate) path: PathBuf,
    pub(crate) mode: RecordMode,
    pub(crate) matching: MatchConfig,
    pub(crate) security: SecurityConfig,
}

impl RecorderBuilder {
    pub(crate) fn new(path: PathBuf) -> Self {
        Self {
            path,
            mode: RecordMode::Once,
            matching: MatchConfig::default(),
            security: SecurityConfig::default(),
        }
    }

    /// Select the record mode.
    pub fn record_mode(mut self, mode: RecordMode) -> Self {
        self.mode = mode;
        self
    }

    /// Select the HTTP request fields used for matching.
    pub fn match_on<I, S>(mut self, fields: I) -> Result<Self>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.matching
            .set_match_on(fields.into_iter().map(Into::into).collect())?;
        Ok(self)
    }

    /// Ignore dot-separated JSON paths while using the `json_body` matcher.
    pub fn ignore_json_paths<I, S>(mut self, paths: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.matching.ignore_json_paths = paths.into_iter().map(Into::into).collect();
        self
    }

    /// Add header or gRPC metadata names to the safe filtering defaults.
    pub fn filter_headers<I, S>(mut self, names: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        extend_unique(&mut self.security.filter_headers, names);
        self
    }

    /// Add URI query parameter names to the safe filtering defaults.
    pub fn filter_query_parameters<I, S>(mut self, names: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        extend_unique(&mut self.security.filter_query_parameters, names);
        self
    }

    /// Add JSON or text field patterns to the safe filtering defaults.
    pub fn body_scrub_patterns<I, S>(mut self, patterns: I) -> Result<Self>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut combined = self.security.body_scrub_patterns.clone();
        extend_unique(&mut combined, patterns);
        self.security.set_body_scrub_patterns(combined)?;
        Ok(self)
    }

    /// Change the placeholder written in place of filtered values.
    pub fn filter_replacement(mut self, replacement: impl Into<String>) -> Self {
        self.security.replacement = replacement.into();
        self
    }

    /// Load or initialize the cassette.
    pub fn build(self) -> Result<Recorder> {
        Recorder::from_builder(self)
    }
}

fn extend_unique<I, S>(values: &mut Vec<String>, extra: I)
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    for value in extra {
        let value = value.into();
        if !values
            .iter()
            .any(|existing| existing.eq_ignore_ascii_case(&value))
        {
            values.push(value);
        }
    }
}

pub(crate) fn path_text(path: &Path) -> Result<&str> {
    path.to_str().ok_or_else(|| {
        Error::InvalidTransportData(format!("cassette path is not valid UTF-8: {path:?}"))
    })
}
