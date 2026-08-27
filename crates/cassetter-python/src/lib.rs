//! PyO3 bindings for `cassetter-core`.
//!
//! Every type here is a thin newtype over the corresponding core type. All
//! format, matching, security, and body-processing logic lives in the core
//! crate so the Python and Node bindings cannot drift apart.

mod convert;

use std::collections::HashMap;

use cassetter_core as core;
use convert::{depythonize_checked, to_pyerr};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};

type Headers = HashMap<String, Vec<String>>;

// --- Body ---

/// A request or response body, typed as `json`, `text`, `binary`, or `none`.
#[pyclass(frozen, eq, from_py_object, name = "Body", module = "cassetter._core")]
#[derive(Clone, Debug, PartialEq)]
pub struct Body(pub core::protocol::http::Body);

#[pymethods]
impl Body {
    /// Build a body of `body_type` from `content`.
    #[new]
    #[pyo3(signature = (body_type, content=None))]
    fn new(body_type: String, content: Option<Bound<'_, PyAny>>) -> PyResult<Self> {
        use core::protocol::http::BodyContent;
        let inner = match body_type.as_str() {
            "json" => {
                let obj =
                    content.ok_or_else(|| PyValueError::new_err("JSON body requires content"))?;
                BodyContent::Json(depythonize_checked(&obj)?)
            }
            "text" => {
                let obj =
                    content.ok_or_else(|| PyValueError::new_err("text body requires content"))?;
                BodyContent::Text(obj.extract()?)
            }
            "binary" => {
                let obj =
                    content.ok_or_else(|| PyValueError::new_err("binary body requires content"))?;
                BodyContent::Binary(obj.extract()?)
            }
            "none" => BodyContent::None,
            _ => {
                return Err(PyValueError::new_err(format!(
                    "unknown body type: {body_type}"
                )))
            }
        };
        Ok(Body(core::protocol::http::Body { body_type, inner }))
    }

    /// Which of `json`, `text`, `binary`, or `none` this body holds.
    #[getter]
    fn body_type(&self) -> &str {
        &self.0.body_type
    }

    /// The body's value: parsed JSON, a string, bytes, or `None`.
    #[getter]
    fn content(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        use core::protocol::http::BodyContent;
        match &self.0.inner {
            BodyContent::Json(v) => Ok(pythonize::pythonize(py, v)?.into()),
            BodyContent::Text(s) => Ok(PyString::new(py, s).into()),
            BodyContent::Binary(b) => Ok(PyBytes::new(py, b).into()),
            BodyContent::None => Ok(py.None()),
        }
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- HTTP ---

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "HttpRequest",
    module = "cassetter._core"
)]
/// A recorded HTTP request. Frozen: use `replace()` to derive a copy.
#[derive(Clone, Debug, PartialEq)]
pub struct HttpRequest(pub core::protocol::http::HttpRequest);

#[pymethods]
impl HttpRequest {
    /// Build a request. `headers` and `body` default to empty.
    #[new]
    #[pyo3(signature = (method, uri, headers=None, body=None))]
    fn new(method: String, uri: String, headers: Option<Headers>, body: Option<Body>) -> Self {
        HttpRequest(core::protocol::http::HttpRequest::new(
            method,
            uri,
            headers,
            body.map(|b| b.0),
        ))
    }

    /// The method this request was made with.
    #[getter]
    fn method(&self) -> &str {
        &self.0.method
    }

    /// The URI, as recorded - filtered query parameters already replaced.
    #[getter]
    fn uri(&self) -> &str {
        &self.0.uri
    }

    /// Headers, each name mapped to the list of values sent under it.
    #[getter]
    fn headers(&self) -> Headers {
        self.0.headers.clone()
    }

    /// The body, as recorded.
    #[getter]
    fn body(&self) -> Body {
        Body(self.0.body.clone())
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, method=None, uri=None, headers=None, body=None))]
    fn replace(
        &self,
        method: Option<String>,
        uri: Option<String>,
        headers: Option<Headers>,
        body: Option<Body>,
    ) -> Self {
        HttpRequest(core::protocol::http::HttpRequest {
            method: method.unwrap_or_else(|| self.0.method.clone()),
            uri: uri.unwrap_or_else(|| self.0.uri.clone()),
            headers: headers.unwrap_or_else(|| self.0.headers.clone()),
            body: body.map(|b| b.0).unwrap_or_else(|| self.0.body.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "HttpResponse",
    module = "cassetter._core"
)]
/// A recorded HTTP response. Frozen: use `replace()` to derive a copy.
#[derive(Clone, Debug, PartialEq)]
pub struct HttpResponse(pub core::protocol::http::HttpResponse);

#[pymethods]
impl HttpResponse {
    /// Build a response. `headers` and `body` default to empty.
    #[new]
    #[pyo3(signature = (status, headers=None, body=None))]
    fn new(status: u16, headers: Option<Headers>, body: Option<Body>) -> Self {
        HttpResponse(core::protocol::http::HttpResponse::new(
            status,
            headers,
            body.map(|b| b.0),
        ))
    }

    /// The HTTP status code.
    #[getter]
    fn status(&self) -> u16 {
        self.0.status
    }

    /// Headers, each name mapped to the list of values sent under it.
    #[getter]
    fn headers(&self) -> Headers {
        self.0.headers.clone()
    }

    /// The body, as recorded.
    #[getter]
    fn body(&self) -> Body {
        Body(self.0.body.clone())
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, status=None, headers=None, body=None))]
    fn replace(&self, status: Option<u16>, headers: Option<Headers>, body: Option<Body>) -> Self {
        HttpResponse(core::protocol::http::HttpResponse {
            status: status.unwrap_or(self.0.status),
            headers: headers.unwrap_or_else(|| self.0.headers.clone()),
            body: body.map(|b| b.0).unwrap_or_else(|| self.0.body.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "HttpInteraction",
    module = "cassetter._core"
)]
/// One recorded request/response pair.
#[derive(Clone, Debug, PartialEq)]
pub struct HttpInteraction(pub core::protocol::http::HttpInteraction);

#[pymethods]
impl HttpInteraction {
    /// Pair a request and response with the time they were recorded.
    #[new]
    fn new(request: HttpRequest, response: HttpResponse, recorded_at: String) -> Self {
        HttpInteraction(core::protocol::http::HttpInteraction::new(
            request.0,
            response.0,
            recorded_at,
        ))
    }

    /// The request side of this interaction.
    #[getter]
    fn request(&self) -> HttpRequest {
        HttpRequest(self.0.request.clone())
    }

    /// The response side of this interaction.
    #[getter]
    fn response(&self) -> HttpResponse {
        HttpResponse(self.0.response.clone())
    }

    /// When this was recorded, ISO 8601.
    #[getter]
    fn recorded_at(&self) -> &str {
        &self.0.recorded_at
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, request=None, response=None, recorded_at=None))]
    fn replace(
        &self,
        request: Option<HttpRequest>,
        response: Option<HttpResponse>,
        recorded_at: Option<String>,
    ) -> Self {
        HttpInteraction(core::protocol::http::HttpInteraction {
            request: request
                .map(|r| r.0)
                .unwrap_or_else(|| self.0.request.clone()),
            response: response
                .map(|r| r.0)
                .unwrap_or_else(|| self.0.response.clone()),
            recorded_at: recorded_at.unwrap_or_else(|| self.0.recorded_at.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- gRPC ---

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "GrpcRequest",
    module = "cassetter._core"
)]
/// A recorded gRPC request, body held as the raw protobuf bytes.
#[derive(Clone, Debug, PartialEq)]
pub struct GrpcRequest(pub core::protocol::grpc::GrpcRequest);

#[pymethods]
impl GrpcRequest {
    /// Build a gRPC request. `metadata` and `body` default to empty.
    #[new]
    #[pyo3(signature = (method, metadata=None, body=None))]
    fn new(method: String, metadata: Option<Headers>, body: Option<Body>) -> Self {
        GrpcRequest(core::protocol::grpc::GrpcRequest::new(
            method,
            metadata,
            body.map(|b| b.0),
        ))
    }

    /// The method this request was made with.
    #[getter]
    fn method(&self) -> &str {
        &self.0.method
    }

    /// Metadata, each name mapped to the list of values sent under it.
    #[getter]
    fn metadata(&self) -> Headers {
        self.0.metadata.clone()
    }

    /// The body, as recorded.
    #[getter]
    fn body(&self) -> Body {
        Body(self.0.body.clone())
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, method=None, metadata=None, body=None))]
    fn replace(
        &self,
        method: Option<String>,
        metadata: Option<Headers>,
        body: Option<Body>,
    ) -> Self {
        GrpcRequest(core::protocol::grpc::GrpcRequest {
            method: method.unwrap_or_else(|| self.0.method.clone()),
            metadata: metadata.unwrap_or_else(|| self.0.metadata.clone()),
            body: body.map(|b| b.0).unwrap_or_else(|| self.0.body.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "GrpcResponse",
    module = "cassetter._core"
)]
/// A recorded gRPC response, with its status and trailing metadata.
#[derive(Clone, Debug, PartialEq)]
pub struct GrpcResponse(pub core::protocol::grpc::GrpcResponse);

#[pymethods]
impl GrpcResponse {
    /// Build a gRPC response, defaulting the message to `OK`.
    #[new]
    #[pyo3(signature = (status_code, status_message=None, metadata=None, body=None))]
    fn new(
        status_code: u32,
        status_message: Option<String>,
        metadata: Option<Headers>,
        body: Option<Body>,
    ) -> Self {
        GrpcResponse(core::protocol::grpc::GrpcResponse::new(
            status_code,
            status_message,
            metadata,
            body.map(|b| b.0),
        ))
    }

    /// The gRPC status code, 0 for OK.
    #[getter]
    fn status_code(&self) -> u32 {
        self.0.status_code
    }

    /// The gRPC status message.
    #[getter]
    fn status_message(&self) -> &str {
        &self.0.status_message
    }

    /// Metadata, each name mapped to the list of values sent under it.
    #[getter]
    fn metadata(&self) -> Headers {
        self.0.metadata.clone()
    }

    /// The body, as recorded.
    #[getter]
    fn body(&self) -> Body {
        Body(self.0.body.clone())
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, status_code=None, status_message=None, metadata=None, body=None))]
    fn replace(
        &self,
        status_code: Option<u32>,
        status_message: Option<String>,
        metadata: Option<Headers>,
        body: Option<Body>,
    ) -> Self {
        GrpcResponse(core::protocol::grpc::GrpcResponse {
            status_code: status_code.unwrap_or(self.0.status_code),
            status_message: status_message.unwrap_or_else(|| self.0.status_message.clone()),
            metadata: metadata.unwrap_or_else(|| self.0.metadata.clone()),
            body: body.map(|b| b.0).unwrap_or_else(|| self.0.body.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "GrpcInteraction",
    module = "cassetter._core"
)]
/// One recorded gRPC call, optionally with a readable `json_debug`.
#[derive(Clone, Debug, PartialEq)]
pub struct GrpcInteraction(pub core::protocol::grpc::GrpcInteraction);

#[pymethods]
impl GrpcInteraction {
    /// Pair a gRPC request and response with the time they were recorded.
    #[new]
    #[pyo3(signature = (request, response, recorded_at, json_debug=None))]
    fn new(
        request: GrpcRequest,
        response: GrpcResponse,
        recorded_at: String,
        json_debug: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let debug_val = match json_debug {
            Some(obj) if !obj.is_none() => Some(depythonize_checked(&obj)?),
            _ => None,
        };
        Ok(GrpcInteraction(core::protocol::grpc::GrpcInteraction::new(
            request.0,
            response.0,
            recorded_at,
            debug_val,
        )))
    }

    /// A readable rendering of the protobuf payloads, when available.
    #[getter]
    fn json_debug(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.0.json_debug {
            Some(v) => Ok(pythonize::pythonize(py, v)?.into()),
            None => Ok(py.None()),
        }
    }

    /// The request side of this interaction.
    #[getter]
    fn request(&self) -> GrpcRequest {
        GrpcRequest(self.0.request.clone())
    }

    /// The response side of this interaction.
    #[getter]
    fn response(&self) -> GrpcResponse {
        GrpcResponse(self.0.response.clone())
    }

    /// When this was recorded, ISO 8601.
    #[getter]
    fn recorded_at(&self) -> &str {
        &self.0.recorded_at
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, request=None, response=None, recorded_at=None, json_debug=None))]
    fn replace(
        &self,
        request: Option<GrpcRequest>,
        response: Option<GrpcResponse>,
        recorded_at: Option<String>,
        json_debug: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let debug_val = match json_debug {
            Some(obj) if !obj.is_none() => Some(depythonize_checked(&obj)?),
            Some(_) => None,
            None => self.0.json_debug.clone(),
        };
        Ok(GrpcInteraction(core::protocol::grpc::GrpcInteraction {
            request: request
                .map(|r| r.0)
                .unwrap_or_else(|| self.0.request.clone()),
            response: response
                .map(|r| r.0)
                .unwrap_or_else(|| self.0.response.clone()),
            json_debug: debug_val,
            recorded_at: recorded_at.unwrap_or_else(|| self.0.recorded_at.clone()),
        }))
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- WebSocket ---

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "WsFrame",
    module = "cassetter._core"
)]
/// A single WebSocket frame, with the offset it arrived at.
#[derive(Clone, Debug, PartialEq)]
pub struct WsFrame(pub core::protocol::ws::WsFrame);

#[pymethods]
impl WsFrame {
    /// Build a frame at `offset_ms` into the connection.
    #[new]
    #[pyo3(signature = (direction, frame_type, body, offset_ms=0))]
    fn new(direction: String, frame_type: String, body: Body, offset_ms: u64) -> Self {
        WsFrame(core::protocol::ws::WsFrame::new(
            direction, frame_type, body.0, offset_ms,
        ))
    }

    /// `send` for a frame this side sent, `recv` for one it received.
    #[getter]
    fn direction(&self) -> &str {
        &self.0.direction
    }

    /// `text` or `binary`.
    #[getter]
    fn frame_type(&self) -> &str {
        &self.0.frame_type
    }

    /// The body, as recorded.
    #[getter]
    fn body(&self) -> Body {
        Body(self.0.body.clone())
    }

    /// Milliseconds after the connection opened that this frame moved.
    #[getter]
    fn offset_ms(&self) -> u64 {
        self.0.offset_ms
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, direction=None, frame_type=None, body=None, offset_ms=None))]
    fn replace(
        &self,
        direction: Option<String>,
        frame_type: Option<String>,
        body: Option<Body>,
        offset_ms: Option<u64>,
    ) -> Self {
        WsFrame(core::protocol::ws::WsFrame {
            direction: direction.unwrap_or_else(|| self.0.direction.clone()),
            frame_type: frame_type.unwrap_or_else(|| self.0.frame_type.clone()),
            body: body.map(|b| b.0).unwrap_or_else(|| self.0.body.clone()),
            offset_ms: offset_ms.unwrap_or(self.0.offset_ms),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    frozen,
    eq,
    from_py_object,
    name = "WsInteraction",
    module = "cassetter._core"
)]
/// One recorded WebSocket connection and every frame on it.
#[derive(Clone, Debug, PartialEq)]
pub struct WsInteraction(pub core::protocol::ws::WsInteraction);

#[pymethods]
impl WsInteraction {
    /// Build a WebSocket interaction from its frames.
    #[new]
    #[pyo3(signature = (uri, headers=None, frames=None, recorded_at=None))]
    fn new(
        uri: String,
        headers: Option<Headers>,
        frames: Option<Vec<WsFrame>>,
        recorded_at: Option<String>,
    ) -> Self {
        WsInteraction(core::protocol::ws::WsInteraction::new(
            uri,
            headers,
            frames.map(|fs| fs.into_iter().map(|f| f.0).collect()),
            recorded_at,
        ))
    }

    /// The URI, as recorded - filtered query parameters already replaced.
    #[getter]
    fn uri(&self) -> &str {
        &self.0.uri
    }

    /// Headers, each name mapped to the list of values sent under it.
    #[getter]
    fn headers(&self) -> Headers {
        self.0.headers.clone()
    }

    /// Every frame on the connection, in order.
    #[getter]
    fn frames(&self) -> Vec<WsFrame> {
        self.0.frames.iter().cloned().map(WsFrame).collect()
    }

    /// When this was recorded, ISO 8601.
    #[getter]
    fn recorded_at(&self) -> &str {
        &self.0.recorded_at
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, uri=None, headers=None, frames=None, recorded_at=None))]
    fn replace(
        &self,
        uri: Option<String>,
        headers: Option<Headers>,
        frames: Option<Vec<WsFrame>>,
        recorded_at: Option<String>,
    ) -> Self {
        WsInteraction(core::protocol::ws::WsInteraction {
            uri: uri.unwrap_or_else(|| self.0.uri.clone()),
            headers: headers.unwrap_or_else(|| self.0.headers.clone()),
            frames: frames
                .map(|fs| fs.into_iter().map(|f| f.0).collect())
                .unwrap_or_else(|| self.0.frames.clone()),
            recorded_at: recorded_at.unwrap_or_else(|| self.0.recorded_at.clone()),
        })
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- Configuration ---

/// Which fields a request is matched on, and which JSON paths to ignore.
#[pyclass(skip_from_py_object, name = "MatchConfig", module = "cassetter._core")]
#[derive(Clone, Debug)]
pub struct MatchConfig(pub core::matching::config::MatchConfig);

#[pymethods]
impl MatchConfig {
    /// Build a match config, defaulting to matching on method and URI.
    #[new]
    #[pyo3(signature = (match_on=None, ignore_json_paths=None))]
    fn new(
        match_on: Option<Vec<String>>,
        ignore_json_paths: Option<Vec<String>>,
    ) -> PyResult<Self> {
        core::matching::config::MatchConfig::new(match_on, ignore_json_paths)
            .map(MatchConfig)
            .map_err(to_pyerr)
    }

    /// The fields a request is matched on.
    #[getter]
    fn match_on(&self) -> Vec<String> {
        self.0.match_on.clone()
    }

    /// Validate on assignment too: an unvalidated matcher name would make
    /// matching reject every request, and before it failed closed it served an
    /// arbitrary recorded response to any request at all.
    #[setter]
    fn set_match_on(&mut self, match_on: Vec<String>) -> PyResult<()> {
        self.0.set_match_on(match_on).map_err(to_pyerr)
    }

    /// JSON paths ignored by the `json_body` matcher.
    #[getter]
    fn ignore_json_paths(&self) -> Vec<String> {
        self.0.ignore_json_paths.clone()
    }

    /// Set jSON paths ignored by the `json_body` matcher.
    #[setter]
    fn set_ignore_json_paths(&mut self, paths: Vec<String>) {
        self.0.ignore_json_paths = paths;
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

#[pyclass(
    skip_from_py_object,
    name = "SecurityConfig",
    module = "cassetter._core"
)]
/// What gets filtered out of a cassette at write time.
#[derive(Clone, Debug)]
pub struct SecurityConfig(pub core::security::SecurityConfig);

#[pymethods]
impl SecurityConfig {
    #[new]
    #[pyo3(signature = (
        filter_headers=None,
        filter_query_parameters=None,
        body_scrub_patterns=None,
        replacement=None,
    ))]
    /// Build a security config. Each list *adds to* the built-in defaults.
    fn new(
        filter_headers: Option<Vec<String>>,
        filter_query_parameters: Option<Vec<String>>,
        body_scrub_patterns: Option<Vec<String>>,
        replacement: Option<String>,
    ) -> PyResult<Self> {
        core::security::SecurityConfig::new(
            filter_headers,
            filter_query_parameters,
            body_scrub_patterns,
            replacement,
        )
        .map(SecurityConfig)
        .map_err(to_pyerr)
    }

    /// Header names stripped at write time.
    #[getter]
    fn filter_headers(&self) -> Vec<String> {
        self.0.filter_headers.clone()
    }

    /// Set header names stripped at write time.
    #[setter]
    fn set_filter_headers(&mut self, v: Vec<String>) {
        self.0.filter_headers = v;
    }

    /// Query parameter names whose values are replaced at write time.
    #[getter]
    fn filter_query_parameters(&self) -> Vec<String> {
        self.0.filter_query_parameters.clone()
    }

    /// Set query parameter names whose values are replaced at write time.
    #[setter]
    fn set_filter_query_parameters(&mut self, v: Vec<String>) {
        self.0.filter_query_parameters = v;
    }

    /// Body field names whose values are replaced at write time.
    #[getter]
    fn body_scrub_patterns(&self) -> Vec<String> {
        self.0.body_scrub_patterns.clone()
    }

    /// Set body field names whose values are replaced at write time.
    #[setter]
    fn set_body_scrub_patterns(&mut self, patterns: Vec<String>) -> PyResult<()> {
        self.0.set_body_scrub_patterns(patterns).map_err(to_pyerr)
    }

    /// The placeholder written in place of a filtered value.
    #[getter]
    fn replacement(&self) -> &str {
        &self.0.replacement
    }

    /// Set the placeholder written in place of a filtered value.
    #[setter]
    fn set_replacement(&mut self, v: String) {
        self.0.replacement = v;
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- Cassette ---

/// A cassette's interactions and their played state.
#[pyclass(skip_from_py_object, name = "Cassette", module = "cassetter._core")]
#[derive(Clone, Debug, Default)]
pub struct Cassette(pub core::cassette::Cassette);

#[pymethods]
impl Cassette {
    /// Start an empty cassette.
    #[new]
    fn new() -> Self {
        Cassette(core::cassette::Cassette::new())
    }

    /// The cassette file format version.
    #[getter]
    fn version(&self) -> u32 {
        self.0.version
    }

    /// Set the cassette file format version.
    #[setter]
    fn set_version(&mut self, v: u32) {
        self.0.version = v;
    }

    // --- HTTP ---

    /// The recorded HTTP interactions.
    #[getter]
    fn interactions(&self) -> Vec<HttpInteraction> {
        self.0
            .interactions
            .iter()
            .cloned()
            .map(HttpInteraction)
            .collect()
    }

    /// Set the recorded HTTP interactions.
    #[setter]
    fn set_interactions(&mut self, interactions: Vec<HttpInteraction>) {
        self.0
            .set_interactions(interactions.into_iter().map(|i| i.0).collect());
    }

    /// Which HTTP interactions have been played, by index.
    #[getter]
    fn played_indices(&self) -> Vec<bool> {
        self.0.played_indices.clone()
    }

    /// Append an HTTP interaction, unplayed.
    fn add_interaction(&mut self, interaction: HttpInteraction) {
        self.0.add_interaction(interaction.0);
    }

    /// Mark an HTTP interaction played. Raises `IndexError` if out of range.
    fn mark_played(&mut self, index: usize) -> PyResult<()> {
        self.0.mark_played(index).map_err(to_pyerr)
    }

    /// How many HTTP interactions have not been played.
    #[getter]
    fn unplayed_count(&self) -> usize {
        self.0.unplayed_count()
    }

    /// Find a matching interaction and mark it played, in one step.
    ///
    /// Matching against the interactions already held in Rust avoids
    /// marshalling the whole cassette across the FFI boundary on every
    /// request, and makes find-then-mark atomic so two threads cannot consume
    /// the same interaction.
    fn take_match(
        &mut self,
        request: &HttpRequest,
        config: &MatchConfig,
    ) -> Option<(usize, HttpInteraction)> {
        self.0
            .take_match(&request.0, &config.0)
            .map(|(idx, i)| (idx, HttpInteraction(i)))
    }

    // --- gRPC ---

    /// The recorded gRPC interactions.
    #[getter]
    fn grpc_interactions(&self) -> Vec<GrpcInteraction> {
        self.0
            .grpc_interactions
            .iter()
            .cloned()
            .map(GrpcInteraction)
            .collect()
    }

    /// Set the recorded gRPC interactions.
    #[setter]
    fn set_grpc_interactions(&mut self, interactions: Vec<GrpcInteraction>) {
        self.0
            .set_grpc_interactions(interactions.into_iter().map(|i| i.0).collect());
    }

    /// Which gRPC interactions have been played, by index.
    #[getter]
    fn grpc_played(&self) -> Vec<bool> {
        self.0.grpc_played.clone()
    }

    /// Append a gRPC interaction, unplayed.
    fn add_grpc_interaction(&mut self, interaction: GrpcInteraction) {
        self.0.add_grpc_interaction(interaction.0);
    }

    /// Mark a gRPC interaction played. Raises `IndexError` if out of range.
    fn mark_grpc_played(&mut self, index: usize) -> PyResult<()> {
        self.0.mark_grpc_played(index).map_err(to_pyerr)
    }

    /// Find a gRPC interaction for `method` and mark it played, in one step.
    fn take_grpc_match(&mut self, method: &str) -> Option<(usize, GrpcInteraction)> {
        self.0
            .take_grpc_match(method)
            .map(|(idx, i)| (idx, GrpcInteraction(i)))
    }

    // --- WebSocket ---

    /// The recorded WebSocket interactions.
    #[getter]
    fn ws_interactions(&self) -> Vec<WsInteraction> {
        self.0
            .ws_interactions
            .iter()
            .cloned()
            .map(WsInteraction)
            .collect()
    }

    /// Set the recorded WebSocket interactions.
    #[setter]
    fn set_ws_interactions(&mut self, interactions: Vec<WsInteraction>) {
        self.0
            .set_ws_interactions(interactions.into_iter().map(|i| i.0).collect());
    }

    /// Which WebSocket interactions have been played, by index.
    #[getter]
    fn ws_played(&self) -> Vec<bool> {
        self.0.ws_played.clone()
    }

    /// Append a WebSocket interaction, unplayed.
    fn add_ws_interaction(&mut self, interaction: WsInteraction) {
        self.0.add_ws_interaction(interaction.0);
    }

    /// Mark a WebSocket interaction played. Raises `IndexError` if out of range.
    fn mark_ws_played(&mut self, index: usize) -> PyResult<()> {
        self.0.mark_ws_played(index).map_err(to_pyerr)
    }

    /// Find a WebSocket interaction for `uri` and mark it played, in one step.
    fn take_ws_match(&mut self, uri: &str) -> Option<(usize, WsInteraction)> {
        self.0
            .take_ws_match(uri)
            .map(|(idx, i)| (idx, WsInteraction(i)))
    }

    // --- Persistence ---

    /// Load a cassette from disk.
    ///
    /// The GIL is released for the whole parse: a multi-megabyte cassette
    /// would otherwise freeze every other thread in the interpreter.
    #[staticmethod]
    fn load(py: Python<'_>, path: &str) -> PyResult<Cassette> {
        py.detach(|| core::cassette::Cassette::load(path))
            .map(Cassette)
            .map_err(to_pyerr)
    }

    /// The order these interactions should be written in.
    #[pyo3(signature = (sort_config=None, record_order=None))]
    fn output_order(
        &self,
        sort_config: Option<&MatchConfig>,
        record_order: Option<Vec<usize>>,
    ) -> Vec<usize> {
        self.0
            .output_order(sort_config.map(|c| &c.0), record_order.as_deref())
    }

    /// Save the cassette to disk, releasing the GIL for serialization and I/O.
    #[pyo3(signature = (path, order=None, mode=None))]
    fn save(
        &self,
        py: Python<'_>,
        path: &str,
        order: Option<Vec<usize>>,
        mode: Option<u32>,
    ) -> PyResult<()> {
        py.detach(|| self.0.save(path, order.as_deref(), mode))
            .map_err(to_pyerr)
    }

    /// How many interactions the cassette holds, across all protocols.
    fn __len__(&self) -> usize {
        self.0.len()
    }

    /// A short, readable rendering for debugging.
    fn __repr__(&self) -> String {
        self.0.describe()
    }
}

// --- Free functions ---

/// Prefer [`Cassette::take_match`], which matches against the interactions
/// already held in Rust instead of marshalling them across the FFI boundary.
#[pyfunction]
fn find_match(
    request: &HttpRequest,
    interactions: Vec<HttpInteraction>,
    played: Vec<bool>,
    config: &MatchConfig,
) -> Option<(usize, HttpInteraction)> {
    let inner: Vec<_> = interactions.into_iter().map(|i| i.0).collect();
    core::matching::find_match(&request.0, &inner, &played, &config.0)
        .map(|(idx, i)| (idx, HttpInteraction(i)))
}

/// Find a gRPC interaction by method. Prefer `Cassette.take_grpc_match`.
#[pyfunction]
fn find_grpc_match(
    method: &str,
    interactions: Vec<GrpcInteraction>,
    played: Vec<bool>,
) -> Option<(usize, GrpcInteraction)> {
    let inner: Vec<_> = interactions.into_iter().map(|i| i.0).collect();
    core::matching::find_grpc_match(method, &inner, &played)
        .map(|(idx, i)| (idx, GrpcInteraction(i)))
}

/// Find a WebSocket interaction by URI. Prefer `Cassette.take_ws_match`.
#[pyfunction]
fn find_ws_match(
    uri: &str,
    interactions: Vec<WsInteraction>,
    played: Vec<bool>,
) -> Option<(usize, WsInteraction)> {
    let inner: Vec<_> = interactions.into_iter().map(|i| i.0).collect();
    core::matching::find_ws_match(uri, &inner, &played).map(|(idx, i)| (idx, WsInteraction(i)))
}

/// Strip filtered headers, query parameters, and body fields from an interaction.
#[pyfunction]
fn scrub_interaction(interaction: &HttpInteraction, config: &SecurityConfig) -> HttpInteraction {
    HttpInteraction(core::security::scrub_interaction(&interaction.0, &config.0))
}

/// Strip filtered metadata and `json_debug` fields from a gRPC interaction.
#[pyfunction]
fn scrub_grpc_interaction(
    interaction: &GrpcInteraction,
    config: &SecurityConfig,
) -> GrpcInteraction {
    GrpcInteraction(core::security::scrub_grpc_interaction(
        &interaction.0,
        &config.0,
    ))
}

/// Strip filtered handshake headers and frame-body fields from a WebSocket interaction.
#[pyfunction]
fn scrub_ws_interaction(interaction: &WsInteraction, config: &SecurityConfig) -> WsInteraction {
    WsInteraction(core::security::scrub_ws_interaction(
        &interaction.0,
        &config.0,
    ))
}

/// Process raw response bytes into a structured Body.
///
/// The GIL is released for the whole pipeline - decompression of a large body
/// takes seconds, and holding the GIL through it freezes the interpreter.
#[pyfunction]
#[pyo3(signature = (raw_bytes, content_type=None, content_encoding=None, max_decompressed=None))]
fn process_body(
    py: Python<'_>,
    raw_bytes: Vec<u8>,
    content_type: Option<String>,
    content_encoding: Option<String>,
    max_decompressed: Option<usize>,
) -> PyResult<Body> {
    py.detach(|| {
        core::body::process_body(
            raw_bytes,
            content_type.as_deref(),
            content_encoding.as_deref(),
            max_decompressed.unwrap_or(core::body::compression::DEFAULT_MAX_DECOMPRESSED),
        )
    })
    .map(Body)
    .map_err(to_pyerr)
}

// Declared free-threading safe deliberately, not by inheriting PyO3's default:
// the crate has no `unsafe`, no mutable statics, and the only shared mutable
// state is `Cassette`, whose match-and-mark step is a single atomic call
// guarded by PyO3's borrow checker.
#[pymodule(gil_used = false)]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // HTTP protocol types
    m.add_class::<Body>()?;
    m.add_class::<HttpRequest>()?;
    m.add_class::<HttpResponse>()?;
    m.add_class::<HttpInteraction>()?;

    // gRPC protocol types
    m.add_class::<GrpcRequest>()?;
    m.add_class::<GrpcResponse>()?;
    m.add_class::<GrpcInteraction>()?;

    // WebSocket protocol types
    m.add_class::<WsFrame>()?;
    m.add_class::<WsInteraction>()?;

    // Cassette
    m.add_class::<Cassette>()?;

    // Matching
    m.add_class::<MatchConfig>()?;
    m.add_function(wrap_pyfunction!(find_match, m)?)?;
    m.add_function(wrap_pyfunction!(find_grpc_match, m)?)?;
    m.add_function(wrap_pyfunction!(find_ws_match, m)?)?;

    // Security
    m.add_class::<SecurityConfig>()?;
    m.add_function(wrap_pyfunction!(scrub_interaction, m)?)?;
    m.add_function(wrap_pyfunction!(scrub_grpc_interaction, m)?)?;
    m.add_function(wrap_pyfunction!(scrub_ws_interaction, m)?)?;

    // Body processing
    m.add_function(wrap_pyfunction!(process_body, m)?)?;

    Ok(())
}
