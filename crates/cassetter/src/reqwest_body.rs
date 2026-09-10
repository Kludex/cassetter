use std::collections::HashMap;

use cassetter_core::protocol::http::{Body, BodyContent, HttpResponse};
use http_body_util::BodyExt;
use reqwest::{Request, Response, ResponseBuilderExt};

use crate::{Error, Result};

pub(crate) async fn collect_request_body(request: &mut Request) -> Result<bytes::Bytes> {
    let Some(body) = request.body_mut().take() else {
        return Ok(bytes::Bytes::new());
    };
    let collected = body
        .collect()
        .await
        .map_err(|error| Error::InvalidTransportData(format!("read HTTP request body: {error}")))?;
    let bytes = collected.to_bytes();
    *request.body_mut() = Some(reqwest::Body::from(bytes.clone()));
    Ok(bytes)
}

pub(crate) fn headers_to_map(headers: &reqwest::header::HeaderMap) -> HashMap<String, Vec<String>> {
    let mut output = HashMap::new();
    for (name, value) in headers {
        if let Ok(value) = value.to_str() {
            output
                .entry(name.as_str().to_string())
                .or_insert_with(Vec::new)
                .push(value.to_string());
        }
    }
    output
}

pub(crate) fn replay_response(url: reqwest::Url, response: HttpResponse) -> Result<Response> {
    let mut headers = reqwest::header::HeaderMap::new();
    for (name, values) in response.headers {
        let name = reqwest::header::HeaderName::try_from(name).map_err(|error| {
            Error::InvalidTransportData(format!("invalid recorded HTTP header name: {error}"))
        })?;
        for value in values {
            headers.append(
                name.clone(),
                reqwest::header::HeaderValue::try_from(value).map_err(|error| {
                    Error::InvalidTransportData(format!(
                        "invalid recorded HTTP header value: {error}"
                    ))
                })?,
            );
        }
    }
    build_response(
        reqwest::StatusCode::from_u16(response.status).map_err(|error| {
            Error::InvalidTransportData(format!("invalid recorded HTTP status: {error}"))
        })?,
        headers,
        body_bytes(response.body)?,
        url,
    )
}

pub(crate) fn build_response(
    status: reqwest::StatusCode,
    headers: reqwest::header::HeaderMap,
    body: Vec<u8>,
    url: reqwest::Url,
) -> Result<Response> {
    let mut response = http::Response::builder()
        .status(status)
        .url(url)
        .body(reqwest::Body::from(body))
        .map_err(|error| Error::InvalidTransportData(format!("build HTTP response: {error}")))?;
    *response.headers_mut() = headers;
    Ok(response.into())
}

pub(crate) fn header<'a>(headers: &'a HashMap<String, Vec<String>>, name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(candidate, _)| candidate.eq_ignore_ascii_case(name))
        .and_then(|(_, values)| values.first())
        .map(String::as_str)
}

fn body_bytes(body: Body) -> Result<Vec<u8>> {
    match body.inner {
        BodyContent::None => Ok(Vec::new()),
        BodyContent::Binary(bytes) => Ok(bytes),
        BodyContent::Text(text) => Ok(text.into_bytes()),
        BodyContent::Json(value) => serde_json::to_vec(&value).map_err(|error| {
            Error::InvalidTransportData(format!("encode recorded JSON body: {error}"))
        }),
    }
}
