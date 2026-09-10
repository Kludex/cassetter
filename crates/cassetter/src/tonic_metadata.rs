use std::collections::HashMap;

use http::HeaderMap;

use crate::Error;

pub(crate) fn grpc_status(headers: &HeaderMap, trailers: &HeaderMap) -> (u32, String) {
    let status = trailers
        .get("grpc-status")
        .or_else(|| headers.get("grpc-status"))
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    let message = trailers
        .get("grpc-message")
        .or_else(|| headers.get("grpc-message"))
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            percent_encoding::percent_decode_str(value)
                .decode_utf8_lossy()
                .into_owned()
        })
        .unwrap_or_else(|| {
            if status == 0 {
                "OK".to_string()
            } else {
                String::new()
            }
        });
    (status, message)
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
