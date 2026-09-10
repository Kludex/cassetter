//! Explicit [`tonic`] transport integration for unary calls.

use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};

use bytes::Bytes;
use cassetter_core::protocol::grpc::{GrpcInteraction, GrpcRequest, GrpcResponse};
use cassetter_core::protocol::http::Body;
use http::{Request, Response};
use http_body::Body as HttpBody;
use http_body_util::BodyExt;
use tower_service::Service;

use crate::recorder::{recorded_at, Action};
use crate::tonic_body::{
    decode_grpc_frame, decode_optional_grpc_frame, replay_response, FramesBody,
};
use crate::tonic_metadata::{grpc_status, merge_metadata, metadata_to_map};
use crate::{Error, Recorder};

type BoxError = Box<dyn std::error::Error + Send + Sync>;
type BoxFuture<T> = Pin<Box<dyn Future<Output = T> + Send>>;

/// A `tonic` service that records and replays unary RPCs.
///
/// Pass this service to a generated client's `new` constructor. Clones share
/// the supplied [`Recorder`], while separately built recorders remain isolated.
#[derive(Clone, Debug)]
pub struct GrpcService<S> {
    inner: S,
    recorder: Recorder,
}

impl<S> GrpcService<S> {
    /// Wrap a channel or another compatible `tonic` transport.
    pub fn new(inner: S, recorder: Recorder) -> Self {
        Self { inner, recorder }
    }

    /// Return the wrapped transport.
    pub fn inner(&self) -> &S {
        &self.inner
    }
}

impl<S, B> Service<Request<::tonic::body::Body>> for GrpcService<S>
where
    S: Service<Request<::tonic::body::Body>, Response = Response<B>> + Clone + Send + 'static,
    S::Future: Send + 'static,
    S::Error: Into<BoxError>,
    B: HttpBody<Data = Bytes> + Send + 'static,
    B::Error: Into<BoxError>,
{
    type Response = Response<::tonic::body::Body>;
    type Error = BoxError;
    type Future = BoxFuture<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, request: Request<::tonic::body::Body>) -> Self::Future {
        let replacement = self.inner.clone();
        let mut inner = std::mem::replace(&mut self.inner, replacement);
        let recorder = self.recorder.clone();

        Box::pin(async move {
            let (parts, body) = request.into_parts();
            let collected = body.collect().await.map_err(boxed)?;
            if collected.trailers().is_some() {
                return Err(boxed(Error::InvalidTransportData(
                    "gRPC request trailers are not supported".to_string(),
                )));
            }
            let framed_request = collected.to_bytes();
            let request_body = decode_grpc_frame(&framed_request).map_err(boxed)?;
            let method = parts.uri.path().to_string();
            let recorded_request = GrpcRequest::new(
                method,
                Some(metadata_to_map(&parts.headers).map_err(boxed)?),
                Some(Body::binary(request_body)),
            );

            match recorder.prepare_grpc(&recorded_request).map_err(boxed)? {
                Action::Replay(interaction) => replay_response(interaction.response).map_err(boxed),
                Action::Record(order) => {
                    let request = Request::from_parts(
                        parts,
                        ::tonic::body::Body::new(http_body_util::Full::new(framed_request)),
                    );
                    if let Err(error) = std::future::poll_fn(|cx| inner.poll_ready(cx)).await {
                        let error = error.into();
                        recorder.fail_recording(order, &error).map_err(boxed)?;
                        return Err(error);
                    }
                    let response = match inner.call(request).await {
                        Ok(response) => response,
                        Err(error) => {
                            let error = error.into();
                            recorder.fail_recording(order, &error).map_err(boxed)?;
                            return Err(error);
                        }
                    };
                    let (response_parts, response_body) = response.into_parts();
                    let collected = match response_body.collect().await {
                        Ok(collected) => collected,
                        Err(error) => {
                            let error = error.into();
                            recorder.fail_recording(order, &error).map_err(boxed)?;
                            return Err(error);
                        }
                    };
                    let trailers = collected.trailers().cloned().unwrap_or_default();
                    let framed_response = collected.to_bytes();
                    let interaction = (|| {
                        let response_payload = decode_optional_grpc_frame(&framed_response)?;
                        let (status_code, status_message) =
                            grpc_status(response_parts.status, &response_parts.headers, &trailers)?;
                        let mut metadata = metadata_to_map(&response_parts.headers)?;
                        merge_metadata(&mut metadata, metadata_to_map(&trailers)?);
                        Ok::<_, Error>(GrpcInteraction::new(
                            recorded_request,
                            GrpcResponse::new(
                                status_code,
                                Some(status_message),
                                Some(metadata),
                                Some(response_payload.map_or_else(Body::none, Body::binary)),
                            ),
                            recorded_at(),
                            None,
                        ))
                    })();
                    let interaction = match interaction {
                        Ok(interaction) => interaction,
                        Err(error) => {
                            recorder.fail_recording(order, &error).map_err(boxed)?;
                            return Err(boxed(error));
                        }
                    };
                    recorder.record_grpc(order, interaction).map_err(boxed)?;
                    Ok(Response::from_parts(
                        response_parts,
                        ::tonic::body::Body::new(FramesBody::new(framed_response, trailers)),
                    ))
                }
            }
        })
    }
}

fn boxed(error: impl Into<BoxError>) -> BoxError {
    error.into()
}
