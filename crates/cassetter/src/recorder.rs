use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};

#[cfg(feature = "tonic")]
use cassetter_core::protocol::grpc::{GrpcInteraction, GrpcRequest};
#[cfg(feature = "reqwest")]
use cassetter_core::protocol::http::{HttpInteraction, HttpRequest, HttpResponse};
#[cfg(feature = "tonic")]
use cassetter_core::security::scrub_grpc_interaction;
#[cfg(feature = "reqwest")]
use cassetter_core::security::scrub_interaction;

use crate::config::{path_text, RecorderBuilder};
#[cfg(feature = "reqwest")]
use crate::recorder_state::retag_content_length;
use crate::recorder_state::State;
use crate::{Error, Result};

/// A concurrency-safe cassette shared by injected HTTP and gRPC transports.
#[must_use = "call Recorder::finish to report persistence and incomplete-recording errors"]
#[derive(Clone, Debug)]
pub struct Recorder {
    inner: Arc<Mutex<State>>,
}

#[cfg(any(feature = "reqwest", feature = "tonic"))]
pub(crate) enum Action<T> {
    Replay(T),
    Record(usize),
}

impl Recorder {
    /// Configure a recorder backed by `path`.
    pub fn builder(path: impl Into<PathBuf>) -> RecorderBuilder {
        RecorderBuilder::new(path.into())
    }

    pub(crate) fn from_builder(builder: RecorderBuilder) -> Result<Self> {
        Ok(Self {
            inner: Arc::new(Mutex::new(State::from_builder(builder)?)),
        })
    }

    /// Persist the cassette and report every failed or incomplete recording.
    ///
    /// Call this after all clients that share the recorder have finished.
    pub async fn finish(&self) -> Result<()> {
        let save_empty = {
            let mut state = self.lock()?;
            let save_empty = !state.finalized && state.save_empty;
            state.finalized = true;
            save_empty
        };

        if save_empty {
            if let Err(error) = self.save() {
                self.remember_error(error.to_string())?;
            }
        }
        let state = self.lock()?;
        let pending = state.pending.values().cloned().collect::<Vec<_>>();
        if !pending.is_empty() && state.errors.is_empty() {
            return Err(Error::Incomplete(pending));
        }
        let mut errors = state.errors.clone();
        errors.extend(
            pending
                .into_iter()
                .map(|request| format!("incomplete recording for {request}")),
        );
        if errors.is_empty() {
            Ok(())
        } else {
            Err(Error::Recording(errors))
        }
    }

    #[cfg(feature = "reqwest")]
    pub(crate) fn prepare_http(&self, request: &HttpRequest) -> Result<Action<HttpResponse>> {
        let mut state = self.lock()?;
        ensure_open(&state)?;
        if state.mode.replays() {
            let probe = scrub_interaction(
                &HttpInteraction::new(
                    request.clone(),
                    HttpResponse::new(0, None, None),
                    String::new(),
                ),
                &state.security,
            );
            let matching = state.matching.clone();
            if let Some((_, interaction)) = state.cassette.take_match(&probe.request, &matching) {
                return Ok(Action::Replay(interaction.response));
            }
        }
        reserve(
            &mut state,
            "HTTP",
            format!("{} {}", request.method, request.uri),
        )
    }

    #[cfg(feature = "tonic")]
    pub(crate) fn prepare_grpc(&self, request: &GrpcRequest) -> Result<Action<GrpcInteraction>> {
        let mut state = self.lock()?;
        ensure_open(&state)?;
        if state.mode.replays() {
            let probe = scrub_grpc_interaction(
                &GrpcInteraction::new(
                    request.clone(),
                    cassetter_core::protocol::grpc::GrpcResponse::new(0, None, None, None),
                    String::new(),
                    None,
                ),
                &state.security,
            );
            if let Some((_, interaction)) = state.cassette.take_grpc_request_match(&probe.request) {
                return Ok(Action::Replay(interaction));
            }
        }
        reserve(&mut state, "gRPC", request.method.clone())
    }

    #[cfg(feature = "reqwest")]
    pub(crate) fn record_http(&self, order: usize, interaction: HttpInteraction) -> Result<()> {
        {
            let mut state = self.lock()?;
            ensure_open(&state)?;
            let mut interaction = scrub_interaction(&interaction, &state.security);
            if let Err(error) = retag_content_length(
                &mut interaction.response.headers,
                &interaction.response.body,
            ) {
                state.pending.remove(&order);
                state.errors.push(error.to_string());
                return Err(error);
            }
            let position = state.http_order.partition_point(|current| *current < order);
            state.http_order.insert(position, order);
            state.cassette.insert_interaction(position, interaction)?;
            state.pending.remove(&order);
            state.save_empty = false;
        }
        self.save().map_err(|error| self.recording_error(error))
    }

    #[cfg(feature = "tonic")]
    pub(crate) fn record_grpc(&self, order: usize, interaction: GrpcInteraction) -> Result<()> {
        {
            let mut state = self.lock()?;
            ensure_open(&state)?;
            let interaction = scrub_grpc_interaction(&interaction, &state.security);
            let position = state.grpc_order.partition_point(|current| *current < order);
            state.grpc_order.insert(position, order);
            state
                .cassette
                .insert_grpc_interaction(position, interaction)?;
            state.pending.remove(&order);
            state.save_empty = false;
        }
        self.save().map_err(|error| self.recording_error(error))
    }

    #[cfg(any(feature = "reqwest", feature = "tonic"))]
    pub(crate) fn fail_recording(&self, order: usize, error: impl ToString) -> Result<()> {
        let mut state = self.lock()?;
        state.pending.remove(&order);
        state.errors.push(error.to_string());
        Ok(())
    }

    #[cfg(any(feature = "reqwest", feature = "tonic"))]
    fn recording_error(&self, error: Error) -> Error {
        let message = error.to_string();
        let _ = self.remember_error(message.clone());
        Error::Recording(vec![message])
    }

    fn remember_error(&self, error: String) -> Result<()> {
        self.lock()?.errors.push(error);
        Ok(())
    }

    fn save(&self) -> Result<()> {
        let state = self.lock()?;
        let order = state
            .cassette
            .output_order(Some(&state.matching), Some(&state.http_order));
        state
            .cassette
            .save(path_text(&state.path)?, Some(&order), state.file_mode)
            .map_err(Error::Core)
    }

    fn lock(&self) -> Result<MutexGuard<'_, State>> {
        self.inner.lock().map_err(|_| {
            Error::InvalidTransportData("cassetter recorder lock was poisoned".to_string())
        })
    }
}

#[cfg(any(feature = "reqwest", feature = "tonic"))]
fn reserve<T>(state: &mut State, protocol: &'static str, request: String) -> Result<Action<T>> {
    if !state.can_record {
        return Err(Error::NoMatch { protocol, request });
    }
    let order = state.next_order;
    state.next_order += 1;
    state.pending.insert(order, format!("{protocol} {request}"));
    Ok(Action::Record(order))
}

#[cfg(any(feature = "reqwest", feature = "tonic"))]
fn ensure_open(state: &State) -> Result<()> {
    if state.finalized {
        Err(Error::Finalized)
    } else {
        Ok(())
    }
}

#[cfg(any(feature = "reqwest", feature = "tonic"))]
pub(crate) fn recorded_at() -> String {
    jiff::Timestamp::now().to_string()
}
