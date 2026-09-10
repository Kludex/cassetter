use std::fmt;

/// An error produced while recording or replaying traffic.
#[derive(Debug)]
pub enum Error {
    /// The cassette configuration or file is invalid.
    Core(cassetter_core::CassetteError),
    /// No recorded interaction matched the request and recording is disabled.
    NoMatch {
        protocol: &'static str,
        request: String,
    },
    /// The recorder was used after finalization.
    Finalized,
    /// One or more requests were still in flight at finalization.
    Incomplete(Vec<String>),
    /// Recording or persistence failed.
    Recording(Vec<String>),
    /// An HTTP body, header, or response could not be represented.
    InvalidTransportData(String),
    /// The live HTTP request failed.
    #[cfg(feature = "reqwest")]
    Reqwest(reqwest::Error),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Core(error) => error.fmt(f),
            Error::NoMatch { protocol, request } => {
                write!(
                    f,
                    "no matching {protocol} cassette interaction for {request}"
                )
            }
            Error::Finalized => f.write_str("cassetter recorder is finalized"),
            Error::Incomplete(requests) => {
                write!(f, "incomplete cassette recordings: {}", requests.join(", "))
            }
            Error::Recording(errors) => {
                write!(f, "cassette recording failed: {}", errors.join("; "))
            }
            Error::InvalidTransportData(message) => f.write_str(message),
            #[cfg(feature = "reqwest")]
            Error::Reqwest(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Error::Core(error) => Some(error),
            #[cfg(feature = "reqwest")]
            Error::Reqwest(error) => Some(error),
            _ => None,
        }
    }
}

impl From<cassetter_core::CassetteError> for Error {
    fn from(error: cassetter_core::CassetteError) -> Self {
        Error::Core(error)
    }
}

#[cfg(feature = "reqwest")]
impl From<reqwest::Error> for Error {
    fn from(error: reqwest::Error) -> Self {
        Error::Reqwest(error)
    }
}

/// The result type returned by this crate.
pub type Result<T> = std::result::Result<T, Error>;
