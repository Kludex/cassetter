//! Async HTTP and gRPC recording and replay for Rust.
//!
//! [`Recorder`] owns one cassette lifecycle. Inject [`reqwest::Client`] or
//! [`tonic::GrpcService`] explicitly into the client under test, then call
//! [`Recorder::finish`] so persistence and incomplete recordings cannot be
//! silently ignored.

mod config;
mod error;
mod recorder;
mod recorder_state;
#[cfg(feature = "reqwest")]
mod reqwest_body;
#[cfg(feature = "tonic")]
mod tonic_body;
#[cfg(feature = "tonic")]
mod tonic_metadata;

#[cfg(feature = "reqwest")]
pub mod reqwest;
#[cfg(feature = "tonic")]
pub mod tonic;

pub use config::{RecordMode, RecorderBuilder};
pub use error::{Error, Result};
pub use recorder::Recorder;
#[cfg(feature = "reqwest")]
pub use reqwest::Client as ReqwestClient;
#[cfg(feature = "tonic")]
pub use tonic::GrpcService;
