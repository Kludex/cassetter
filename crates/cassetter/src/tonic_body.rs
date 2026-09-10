use std::collections::VecDeque;
use std::pin::Pin;
use std::task::{Context, Poll};

use bytes::Bytes;
use cassetter_core::protocol::grpc::GrpcResponse;
use cassetter_core::protocol::http::{Body, BodyContent};
use http::{HeaderMap, Response};
use http_body::{Body as HttpBody, Frame};

use crate::tonic_metadata::map_to_headers;
use crate::Error;

pub(crate) fn replay_response(
    response: GrpcResponse,
) -> Result<Response<::tonic::body::Body>, Error> {
    let framed = match body_bytes(response.body)? {
        Some(payload) => encode_grpc_frame(&payload)?,
        None => Vec::new(),
    };
    let mut metadata = map_to_headers(response.metadata)?;
    metadata.insert(
        "content-type",
        http::HeaderValue::from_static("application/grpc"),
    );
    let mut trailers = metadata.clone();
    trailers.insert(
        "grpc-status",
        http::HeaderValue::try_from(response.status_code.to_string()).map_err(|error| {
            Error::InvalidTransportData(format!("invalid recorded gRPC status: {error}"))
        })?,
    );
    let encoded_message = percent_encoding::utf8_percent_encode(
        &response.status_message,
        percent_encoding::NON_ALPHANUMERIC,
    )
    .to_string();
    trailers.insert(
        "grpc-message",
        http::HeaderValue::try_from(encoded_message).map_err(|error| {
            Error::InvalidTransportData(format!("invalid recorded gRPC status message: {error}"))
        })?,
    );
    Response::builder()
        .status(http::StatusCode::OK)
        .body(::tonic::body::Body::new(FramesBody::new(
            Bytes::from(framed),
            trailers,
        )))
        .map(|mut replay| {
            *replay.headers_mut() = metadata;
            replay
        })
        .map_err(|error| Error::InvalidTransportData(format!("build gRPC response: {error}")))
}

pub(crate) fn decode_grpc_frame(bytes: &[u8]) -> Result<Vec<u8>, Error> {
    if bytes.len() < 5 {
        return Err(Error::InvalidTransportData(
            "gRPC unary request is missing its message frame".to_string(),
        ));
    }
    if bytes[0] != 0 {
        return Err(Error::InvalidTransportData(
            "compressed gRPC messages are not supported".to_string(),
        ));
    }
    let length = u32::from_be_bytes(bytes[1..5].try_into().expect("fixed frame prefix")) as usize;
    if bytes.len() != length + 5 {
        return Err(Error::InvalidTransportData(
            "gRPC transport supports exactly one unary message".to_string(),
        ));
    }
    Ok(bytes[5..].to_vec())
}

pub(crate) fn decode_optional_grpc_frame(bytes: &[u8]) -> Result<Option<Vec<u8>>, Error> {
    if bytes.is_empty() {
        Ok(None)
    } else {
        decode_grpc_frame(bytes).map(Some)
    }
}

fn encode_grpc_frame(payload: &[u8]) -> Result<Vec<u8>, Error> {
    let length = u32::try_from(payload.len()).map_err(|_| {
        Error::InvalidTransportData(
            "recorded gRPC message exceeds the 4 GiB frame limit".to_string(),
        )
    })?;
    let mut frame = Vec::with_capacity(payload.len() + 5);
    frame.push(0);
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(payload);
    Ok(frame)
}

fn body_bytes(body: Body) -> Result<Option<Vec<u8>>, Error> {
    match body.inner {
        BodyContent::None => Ok(None),
        BodyContent::Binary(bytes) => Ok(Some(bytes)),
        _ => Err(Error::InvalidTransportData(
            "recorded gRPC body is not binary".to_string(),
        )),
    }
}

pub(crate) struct FramesBody {
    frames: VecDeque<Frame<Bytes>>,
}

impl FramesBody {
    pub(crate) fn new(data: Bytes, trailers: HeaderMap) -> Self {
        let mut frames = VecDeque::new();
        if !data.is_empty() {
            frames.push_back(Frame::data(data));
        }
        if !trailers.is_empty() {
            frames.push_back(Frame::trailers(trailers));
        }
        Self { frames }
    }
}

impl HttpBody for FramesBody {
    type Data = Bytes;
    type Error = ::tonic::Status;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        Poll::Ready(self.frames.pop_front().map(Ok))
    }

    fn is_end_stream(&self) -> bool {
        self.frames.is_empty()
    }
}
