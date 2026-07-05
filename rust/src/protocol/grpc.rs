use std::collections::HashMap;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use super::http::Body;

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcRequest {
    #[pyo3(get, set)]
    pub method: String,
    #[pyo3(get, set)]
    pub metadata: HashMap<String, Vec<String>>,
    pub body: Body,
}

#[pymethods]
impl GrpcRequest {
    #[new]
    #[pyo3(signature = (method, metadata=None, body=None))]
    fn new(
        method: String,
        metadata: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        GrpcRequest {
            method,
            metadata: metadata.unwrap_or_default(),
            body: body.unwrap_or_else(Body::none),
        }
    }

    #[getter]
    fn body(&self) -> Body {
        self.body.clone()
    }

    #[setter]
    fn set_body(&mut self, body: Body) {
        self.body = body;
    }

    fn __repr__(&self) -> String {
        format!("GrpcRequest(method='{}')", self.method)
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcResponse {
    #[pyo3(get, set)]
    pub status_code: u32,
    #[pyo3(get, set)]
    pub status_message: String,
    #[pyo3(get, set)]
    pub metadata: HashMap<String, Vec<String>>,
    pub body: Body,
}

#[pymethods]
impl GrpcResponse {
    #[new]
    #[pyo3(signature = (status_code, status_message=None, metadata=None, body=None))]
    fn new(
        status_code: u32,
        status_message: Option<String>,
        metadata: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        GrpcResponse {
            status_code,
            status_message: status_message.unwrap_or_else(|| "OK".to_string()),
            metadata: metadata.unwrap_or_default(),
            body: body.unwrap_or_else(Body::none),
        }
    }

    #[getter]
    fn body(&self) -> Body {
        self.body.clone()
    }

    #[setter]
    fn set_body(&mut self, body: Body) {
        self.body = body;
    }

    fn __repr__(&self) -> String {
        format!(
            "GrpcResponse(status_code={}, status_message='{}')",
            self.status_code, self.status_message
        )
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcInteraction {
    pub request: GrpcRequest,
    pub response: GrpcResponse,
    /// Optional human-readable protobuf representation for debugging.
    pub json_debug: Option<serde_json::Value>,
    #[pyo3(get, set)]
    pub recorded_at: String,
}

#[pymethods]
impl GrpcInteraction {
    #[new]
    #[pyo3(signature = (request, response, recorded_at, json_debug=None))]
    fn new(
        py: Python<'_>,
        request: GrpcRequest,
        response: GrpcResponse,
        recorded_at: String,
        json_debug: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let debug_val = match json_debug {
            Some(obj) => {
                let val: serde_json::Value = pythonize::depythonize(obj.bind(py))?;
                Some(val)
            }
            None => None,
        };
        Ok(GrpcInteraction {
            request,
            response,
            json_debug: debug_val,
            recorded_at,
        })
    }

    #[getter]
    fn json_debug(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.json_debug {
            Some(v) => Ok(pythonize::pythonize(py, v)?.into()),
            None => Ok(py.None()),
        }
    }

    #[getter]
    fn request(&self) -> GrpcRequest {
        self.request.clone()
    }

    #[setter]
    fn set_request(&mut self, request: GrpcRequest) {
        self.request = request;
    }

    #[getter]
    fn response(&self) -> GrpcResponse {
        self.response.clone()
    }

    #[setter]
    fn set_response(&mut self, response: GrpcResponse) {
        self.response = response;
    }

    fn __repr__(&self) -> String {
        format!(
            "GrpcInteraction(request={}, response={})",
            self.request.__repr__(),
            self.response.__repr__()
        )
    }
}
