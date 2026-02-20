use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", content = "content")]
pub enum BodyContent {
    #[serde(rename = "json")]
    Json(serde_json::Value),
    #[serde(rename = "text")]
    Text(String),
    #[serde(rename = "binary")]
    Binary(Vec<u8>),
    #[serde(rename = "none")]
    None,
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Body {
    #[pyo3(get)]
    #[serde(rename = "type")]
    pub body_type: String,
    #[serde(flatten)]
    pub inner: BodyContent,
}

#[pymethods]
impl Body {
    #[new]
    #[pyo3(signature = (body_type, content=None))]
    fn new(py: Python<'_>, body_type: String, content: Option<Py<PyAny>>) -> PyResult<Self> {
        let inner = match body_type.as_str() {
            "json" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("JSON body requires content")
                })?;
                let val: serde_json::Value = pythonize::depythonize(&obj.bind(py))?;
                BodyContent::Json(val)
            }
            "text" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("text body requires content")
                })?;
                let s: String = obj.extract(py)?;
                BodyContent::Text(s)
            }
            "binary" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("binary body requires content")
                })?;
                let b: Vec<u8> = obj.extract(py)?;
                BodyContent::Binary(b)
            }
            "none" => BodyContent::None,
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown body type: {body_type}"
                )))
            }
        };
        Ok(Body { body_type, inner })
    }

    #[getter]
    fn content(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.inner {
            BodyContent::Json(v) => Ok(pythonize::pythonize(py, v)?.into()),
            BodyContent::Text(s) => Ok(PyString::new(py, s).into()),
            BodyContent::Binary(b) => Ok(PyBytes::new(py, b).into()),
            BodyContent::None => Ok(py.None()),
        }
    }

    fn __repr__(&self) -> String {
        match &self.inner {
            BodyContent::Json(_) => "Body(type='json', ...)".to_string(),
            BodyContent::Text(s) => {
                let preview = if s.len() > 50 { &s[..50] } else { s };
                format!("Body(type='text', content='{preview}...')")
            }
            BodyContent::Binary(b) => format!("Body(type='binary', len={})", b.len()),
            BodyContent::None => "Body(type='none')".to_string(),
        }
    }
}

impl Body {
    pub fn none() -> Self {
        Body {
            body_type: "none".to_string(),
            inner: BodyContent::None,
        }
    }

    pub fn json(value: serde_json::Value) -> Self {
        Body {
            body_type: "json".to_string(),
            inner: BodyContent::Json(value),
        }
    }

    pub fn text(s: String) -> Self {
        Body {
            body_type: "text".to_string(),
            inner: BodyContent::Text(s),
        }
    }

    pub fn binary(b: Vec<u8>) -> Self {
        Body {
            body_type: "binary".to_string(),
            inner: BodyContent::Binary(b),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpRequest {
    #[pyo3(get, set)]
    pub method: String,
    #[pyo3(get, set)]
    pub uri: String,
    #[pyo3(get, set)]
    pub headers: HashMap<String, Vec<String>>,
    pub body: Body,
}

#[pymethods]
impl HttpRequest {
    #[new]
    #[pyo3(signature = (method, uri, headers=None, body=None))]
    fn new(
        method: String,
        uri: String,
        headers: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        HttpRequest {
            method,
            uri,
            headers: headers.unwrap_or_default(),
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
        format!("HttpRequest(method='{}', uri='{}')", self.method, self.uri)
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpResponse {
    #[pyo3(get, set)]
    pub status: u16,
    #[pyo3(get, set)]
    pub headers: HashMap<String, Vec<String>>,
    pub body: Body,
}

#[pymethods]
impl HttpResponse {
    #[new]
    #[pyo3(signature = (status, headers=None, body=None))]
    fn new(
        status: u16,
        headers: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        HttpResponse {
            status,
            headers: headers.unwrap_or_default(),
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
        format!("HttpResponse(status={})", self.status)
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpInteraction {
    pub request: HttpRequest,
    pub response: HttpResponse,
    #[pyo3(get, set)]
    pub recorded_at: String,
}

#[pymethods]
impl HttpInteraction {
    #[new]
    fn new(request: HttpRequest, response: HttpResponse, recorded_at: String) -> Self {
        HttpInteraction {
            request,
            response,
            recorded_at,
        }
    }

    #[getter]
    fn request(&self) -> HttpRequest {
        self.request.clone()
    }

    #[setter]
    fn set_request(&mut self, request: HttpRequest) {
        self.request = request;
    }

    #[getter]
    fn response(&self) -> HttpResponse {
        self.response.clone()
    }

    #[setter]
    fn set_response(&mut self, response: HttpResponse) {
        self.response = response;
    }

    fn __repr__(&self) -> String {
        format!(
            "HttpInteraction(request={}, response={})",
            self.request.__repr__(),
            self.response.__repr__()
        )
    }
}
