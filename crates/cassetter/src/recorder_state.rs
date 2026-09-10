use std::collections::BTreeMap;
#[cfg(feature = "reqwest")]
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use cassetter_core::cassette::Cassette;
use cassetter_core::matching::config::MatchConfig;
#[cfg(feature = "reqwest")]
use cassetter_core::protocol::http::{Body, BodyContent};
use cassetter_core::security::SecurityConfig;

use crate::config::{path_text, RecordMode, RecorderBuilder};
#[cfg(feature = "reqwest")]
use crate::Error;
use crate::Result;

#[derive(Debug)]
pub(crate) struct State {
    pub(crate) path: PathBuf,
    pub(crate) cassette: Cassette,
    #[cfg_attr(not(any(feature = "reqwest", feature = "tonic")), allow(dead_code))]
    pub(crate) mode: RecordMode,
    #[cfg_attr(not(any(feature = "reqwest", feature = "tonic")), allow(dead_code))]
    pub(crate) can_record: bool,
    pub(crate) matching: MatchConfig,
    #[cfg_attr(not(any(feature = "reqwest", feature = "tonic")), allow(dead_code))]
    pub(crate) security: SecurityConfig,
    #[cfg_attr(not(any(feature = "reqwest", feature = "tonic")), allow(dead_code))]
    pub(crate) next_order: usize,
    pub(crate) http_order: Vec<usize>,
    #[cfg_attr(not(feature = "tonic"), allow(dead_code))]
    pub(crate) grpc_order: Vec<usize>,
    pub(crate) pending: BTreeMap<usize, String>,
    pub(crate) errors: Vec<String>,
    pub(crate) save_empty: bool,
    pub(crate) file_mode: Option<u32>,
    pub(crate) finalized: bool,
}

impl State {
    pub(crate) fn from_builder(builder: RecorderBuilder) -> Result<Self> {
        let exists = builder.path.exists();
        let preserved_mode = file_mode(&builder.path);
        if builder.mode == RecordMode::Rewrite && exists {
            fs::remove_file(&builder.path).map_err(|error| {
                cassetter_core::CassetteError::Io(format!(
                    "remove {}: {error}",
                    builder.path.display()
                ))
            })?;
        }

        let load_existing = exists && !builder.mode.replaces();
        let cassette = if load_existing {
            Cassette::load(path_text(&builder.path)?)?
        } else {
            Cassette::new()
        };
        let can_record = builder.mode.can_record(exists);
        let http_count = cassette.interactions.len();
        let grpc_count = cassette.grpc_interactions.len();
        let next_order = http_count + grpc_count + cassette.ws_interactions.len();

        Ok(Self {
            path: builder.path,
            cassette,
            mode: builder.mode,
            can_record,
            matching: builder.matching,
            security: builder.security,
            next_order,
            http_order: (0..http_count).collect(),
            grpc_order: (0..grpc_count).collect(),
            pending: BTreeMap::new(),
            errors: Vec::new(),
            save_empty: exists && builder.mode == RecordMode::All,
            file_mode: preserved_mode,
            finalized: false,
        })
    }
}

#[cfg(feature = "reqwest")]
pub(crate) fn retag_content_length(
    headers: &mut HashMap<String, Vec<String>>,
    body: &Body,
) -> Result<()> {
    let length = match &body.inner {
        BodyContent::None => return Ok(()),
        BodyContent::Binary(value) => value.len(),
        BodyContent::Text(value) => value.len(),
        BodyContent::Json(value) => serde_json::to_vec(value)
            .map_err(|error| Error::InvalidTransportData(format!("encode JSON body: {error}")))?
            .len(),
    };
    if let Some((_, values)) = headers
        .iter_mut()
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
    {
        *values = vec![length.to_string()];
    }
    Ok(())
}

#[cfg(unix)]
fn file_mode(path: &std::path::Path) -> Option<u32> {
    use std::os::unix::fs::PermissionsExt;

    fs::metadata(path)
        .ok()
        .map(|metadata| metadata.permissions().mode())
}

#[cfg(not(unix))]
fn file_mode(_path: &std::path::Path) -> Option<u32> {
    None
}
