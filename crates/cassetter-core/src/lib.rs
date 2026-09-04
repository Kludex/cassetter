//! Language-agnostic core for cassetter.
//!
//! This crate holds the cassette format (YAML and TOML), request matching,
//! security filtering, and body processing. It has no binding dependencies -
//! `cassetter-python` (PyO3) and `cassetter-node` (napi-rs) are thin wrappers
//! over these types, so every language binding shares one implementation and
//! one definition of the cassette format.

pub mod body;
pub mod cassette;
pub mod interop;
pub mod matching;
pub mod protocol;
pub mod security;

use std::fmt;

/// Errors produced by the core. Bindings map these onto their host language's
/// native exception types.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CassetteError {
    /// No cassette file exists at the given path.
    NotFound(String),
    /// Filesystem read/write failure.
    Io(String),
    /// A cassette could not be parsed or serialized.
    Format(String),
    /// A value was invalid: an unknown matcher, a bad body type, an
    /// uncompilable scrub pattern, a malformed encoding.
    Value(String),
    /// An interaction index was out of range.
    IndexOutOfRange(String),
}

impl fmt::Display for CassetteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let msg = match self {
            CassetteError::NotFound(m)
            | CassetteError::Io(m)
            | CassetteError::Format(m)
            | CassetteError::Value(m)
            | CassetteError::IndexOutOfRange(m) => m,
        };
        f.write_str(msg)
    }
}

impl std::error::Error for CassetteError {}

/// Convenience alias used throughout the core.
pub type Result<T> = std::result::Result<T, CassetteError>;
