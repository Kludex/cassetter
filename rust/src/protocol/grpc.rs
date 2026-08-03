use std::collections::HashMap;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use super::depythonize_checked;
use super::http::Body;

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcRequest {
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
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

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, method=None, metadata=None, body=None))]
    fn replace(
        &self,
        method: Option<String>,
        metadata: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        GrpcRequest {
            method: method.unwrap_or_else(|| self.method.clone()),
            metadata: metadata.unwrap_or_else(|| self.metadata.clone()),
            body: body.unwrap_or_else(|| self.body.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!("GrpcRequest(method={:?})", self.method)
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcResponse {
    #[pyo3(get)]
    pub status_code: u32,
    #[pyo3(get)]
    pub status_message: String,
    #[pyo3(get)]
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

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, status_code=None, status_message=None, metadata=None, body=None))]
    fn replace(
        &self,
        status_code: Option<u32>,
        status_message: Option<String>,
        metadata: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        GrpcResponse {
            status_code: status_code.unwrap_or(self.status_code),
            status_message: status_message.unwrap_or_else(|| self.status_message.clone()),
            metadata: metadata.unwrap_or_else(|| self.metadata.clone()),
            body: body.unwrap_or_else(|| self.body.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "GrpcResponse(status_code={}, status_message={:?})",
            self.status_code, self.status_message
        )
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcInteraction {
    pub request: GrpcRequest,
    pub response: GrpcResponse,
    /// Optional human-readable protobuf representation for debugging.
    pub json_debug: Option<serde_json::Value>,
    #[pyo3(get)]
    pub recorded_at: String,
}

#[pymethods]
impl GrpcInteraction {
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

    #[getter]
    fn response(&self) -> GrpcResponse {
        self.response.clone()
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
            None => self.json_debug.clone(),
        };
        Ok(GrpcInteraction {
            request: request.unwrap_or_else(|| self.request.clone()),
            response: response.unwrap_or_else(|| self.response.clone()),
            json_debug: debug_val,
            recorded_at: recorded_at.unwrap_or_else(|| self.recorded_at.clone()),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "GrpcInteraction(request={}, response={})",
            self.request.__repr__(),
            self.response.__repr__()
        )
    }
}
