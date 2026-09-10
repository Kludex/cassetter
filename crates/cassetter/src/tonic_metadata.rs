use std::collections::HashMap;

use http::HeaderMap;

use crate::Error;

pub(crate) fn grpc_status(
    http_status: http::StatusCode,
    headers: &HeaderMap,
    trailers: &HeaderMap,
) -> Result<(u32, String), Error> {
    let status_header = trailers
        .get("grpc-status")
        .or_else(|| headers.get("grpc-status"));
    let status = match status_header {
        Some(value) => {
            let value = value.to_str().map_err(|error| {
                Error::InvalidTransportData(format!("gRPC status is not text: {error}"))
            })?;
            let status = value.parse::<u32>().map_err(|error| {
                Error::InvalidTransportData(format!("invalid gRPC status {value:?}: {error}"))
            })?;
            if status > 16 {
                return Err(Error::InvalidTransportData(format!(
                    "invalid gRPC status code: {status}"
                )));
            }
            status
        }
        None => status_from_http(http_status),
    };
    let message = trailers
        .get("grpc-message")
        .or_else(|| headers.get("grpc-message"))
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            percent_encoding::percent_decode_str(value)
                .decode_utf8_lossy()
                .into_owned()
        })
        .unwrap_or_else(|| default_status_message(status_header.is_some(), status, http_status));
    Ok((status, message))
}

fn status_from_http(status: http::StatusCode) -> u32 {
    match status {
        http::StatusCode::BAD_REQUEST => 13,
        http::StatusCode::UNAUTHORIZED => 16,
        http::StatusCode::FORBIDDEN => 7,
        http::StatusCode::NOT_FOUND => 12,
        http::StatusCode::TOO_MANY_REQUESTS
        | http::StatusCode::BAD_GATEWAY
        | http::StatusCode::SERVICE_UNAVAILABLE
        | http::StatusCode::GATEWAY_TIMEOUT => 14,
        _ => 2,
    }
}

fn default_status_message(
    explicit_status: bool,
    status: u32,
    http_status: http::StatusCode,
) -> String {
    if explicit_status && status == 0 {
        "OK".to_string()
    } else if explicit_status {
        String::new()
    } else if http_status == http::StatusCode::OK {
        "protocol error: missing grpc-status trailer, stream was terminated without a final status"
            .to_string()
    } else {
        format!(
            "grpc-status header missing, mapped from HTTP status code {}",
            http_status.as_u16()
        )
    }
}

pub(crate) fn metadata_to_map(headers: &HeaderMap) -> Result<HashMap<String, Vec<String>>, Error> {
    let mut metadata = HashMap::new();
    for (name, value) in headers {
        if is_transport_header(name.as_str()) {
            continue;
        }
        let value = value.to_str().map_err(|error| {
            Error::InvalidTransportData(format!("gRPC metadata {name:?} is not text: {error}"))
        })?;
        metadata
            .entry(name.as_str().to_string())
            .or_insert_with(Vec::new)
            .push(value.to_string());
    }
    Ok(metadata)
}

pub(crate) fn map_to_headers(metadata: HashMap<String, Vec<String>>) -> Result<HeaderMap, Error> {
    let mut headers = HeaderMap::new();
    for (name, values) in metadata {
        let name = http::header::HeaderName::try_from(name).map_err(|error| {
            Error::InvalidTransportData(format!("invalid recorded gRPC metadata name: {error}"))
        })?;
        for value in values {
            headers.append(
                name.clone(),
                http::HeaderValue::try_from(value).map_err(|error| {
                    Error::InvalidTransportData(format!(
                        "invalid recorded gRPC metadata value: {error}"
                    ))
                })?,
            );
        }
    }
    Ok(headers)
}

pub(crate) fn merge_metadata(
    target: &mut HashMap<String, Vec<String>>,
    source: HashMap<String, Vec<String>>,
) {
    for (name, values) in source {
        target.entry(name).or_default().extend(values);
    }
}

fn is_transport_header(name: &str) -> bool {
    matches!(
        name,
        "content-type"
            | "content-length"
            | "te"
            | "user-agent"
            | "grpc-status"
            | "grpc-message"
            | "grpc-encoding"
            | "grpc-accept-encoding"
            | "grpc-timeout"
            | "date"
    )
}
