//! Explicit [`reqwest`] client integration.

use cassetter_core::body::compression::DEFAULT_MAX_DECOMPRESSED;
use cassetter_core::body::process_body;
use cassetter_core::protocol::http::{HttpInteraction, HttpRequest, HttpResponse};
use reqwest::{Request, Response};

use crate::recorder::{recorded_at, Action};
use crate::reqwest_body::{
    build_response, collect_request_body, header, headers_to_map, replay_response,
};
use crate::{Error, Recorder, Result};

/// A `reqwest` client that records and replays complete HTTP exchanges.
#[derive(Clone, Debug)]
pub struct Client {
    inner: reqwest::Client,
    recorder: Recorder,
}

impl Client {
    /// Wrap an existing client with an explicit recorder.
    pub fn new(inner: reqwest::Client, recorder: Recorder) -> Self {
        Self { inner, recorder }
    }

    /// Return the wrapped client for building requests with its configuration.
    pub fn inner(&self) -> &reqwest::Client {
        &self.inner
    }

    /// Execute a request, replaying a match, recording the live response, or verifying it against the match.
    pub async fn execute(&self, mut request: Request) -> Result<Response> {
        let request_bytes = collect_request_body(&mut request).await?;
        let headers = headers_to_map(request.headers());
        let recorded_request = HttpRequest::new(
            request.method().as_str().to_string(),
            request.url().as_str().to_string(),
            Some(headers.clone()),
            Some(process_body(
                request_bytes.to_vec(),
                header(&headers, "content-type"),
                header(&headers, "content-encoding"),
                DEFAULT_MAX_DECOMPRESSED,
            )?),
        );

        let verify = self.recorder.verifies()?;
        let action = match self.recorder.prepare_http(&recorded_request)? {
            Action::Replay(response) if !verify => {
                return replay_response(request.url().clone(), response)
            }
            action => action,
        };
        let fail = |error: Error| match &action {
            Action::Record(order) => self
                .recorder
                .fail_recording(*order, &error)
                .err()
                .unwrap_or(error),
            Action::Replay(_) => error,
        };
        let response = self
            .inner
            .execute(request)
            .await
            .map_err(|error| fail(Error::Reqwest(error)))?;
        let status = response.status();
        let response_headers = response.headers().clone();
        let url = response.url().clone();
        let response_bytes = response
            .bytes()
            .await
            .map_err(|error| fail(Error::Reqwest(error)))?;
        let response_headers_map = headers_to_map(&response_headers);
        let response_body = process_body(
            response_bytes.to_vec(),
            header(&response_headers_map, "content-type"),
            header(&response_headers_map, "content-encoding"),
            DEFAULT_MAX_DECOMPRESSED,
        )
        .map_err(|error| fail(Error::Core(error)))?;
        let stored_headers = response_headers_map
            .into_iter()
            .filter(|(name, _)| !name.eq_ignore_ascii_case("content-encoding"))
            .collect();
        let interaction = HttpInteraction::new(
            recorded_request,
            HttpResponse::new(status.as_u16(), Some(stored_headers), Some(response_body)),
            recorded_at(),
        );
        match action {
            Action::Record(order) => self.recorder.record_http(order, interaction)?,
            Action::Replay(recorded) => self.recorder.verify_http(recorded, interaction)?,
        }
        build_response(status, response_headers, response_bytes.to_vec(), url)
    }
}
