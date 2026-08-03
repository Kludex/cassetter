use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use serde::{Deserialize, Serialize};

use super::depythonize_checked;

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

/// Trim a string to at most `max` characters, on a character boundary.
fn preview(s: &str, max: usize) -> (&str, bool) {
    match s.char_indices().nth(max) {
        Some((idx, _)) => (&s[..idx], true),
        None => (s, false),
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
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
    fn new(body_type: String, content: Option<Bound<'_, PyAny>>) -> PyResult<Self> {
        let inner = match body_type.as_str() {
            "json" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("JSON body requires content")
                })?;
                BodyContent::Json(depythonize_checked(&obj)?)
            }
            "text" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("text body requires content")
                })?;
                BodyContent::Text(obj.extract()?)
            }
            "binary" => {
                let obj = content.ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err("binary body requires content")
                })?;
                BodyContent::Binary(obj.extract()?)
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
                let (head, truncated) = preview(s, 50);
                let ellipsis = if truncated { ", ..." } else { "" };
                format!("Body(type='text', content={head:?}{ellipsis})")
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

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpRequest {
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub uri: String,
    #[pyo3(get)]
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

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, method=None, uri=None, headers=None, body=None))]
    fn replace(
        &self,
        method: Option<String>,
        uri: Option<String>,
        headers: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        HttpRequest {
            method: method.unwrap_or_else(|| self.method.clone()),
            uri: uri.unwrap_or_else(|| self.uri.clone()),
            headers: headers.unwrap_or_else(|| self.headers.clone()),
            body: body.unwrap_or_else(|| self.body.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!("HttpRequest(method={:?}, uri={:?})", self.method, self.uri)
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpResponse {
    #[pyo3(get)]
    pub status: u16,
    #[pyo3(get)]
    pub headers: HashMap<String, Vec<String>>,
    pub body: Body,
}

#[pymethods]
impl HttpResponse {
    #[new]
    #[pyo3(signature = (status, headers=None, body=None))]
    fn new(status: u16, headers: Option<HashMap<String, Vec<String>>>, body: Option<Body>) -> Self {
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

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, status=None, headers=None, body=None))]
    fn replace(
        &self,
        status: Option<u16>,
        headers: Option<HashMap<String, Vec<String>>>,
        body: Option<Body>,
    ) -> Self {
        HttpResponse {
            status: status.unwrap_or(self.status),
            headers: headers.unwrap_or_else(|| self.headers.clone()),
            body: body.unwrap_or_else(|| self.body.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!("HttpResponse(status={})", self.status)
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpInteraction {
    pub request: HttpRequest,
    pub response: HttpResponse,
    #[pyo3(get)]
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

    #[getter]
    fn response(&self) -> HttpResponse {
        self.response.clone()
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, request=None, response=None, recorded_at=None))]
    fn replace(
        &self,
        request: Option<HttpRequest>,
        response: Option<HttpResponse>,
        recorded_at: Option<String>,
    ) -> Self {
        HttpInteraction {
            request: request.unwrap_or_else(|| self.request.clone()),
            response: response.unwrap_or_else(|| self.response.clone()),
            recorded_at: recorded_at.unwrap_or_else(|| self.recorded_at.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "HttpInteraction(request={}, response={})",
            self.request.__repr__(),
            self.response.__repr__()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_repr_does_not_append_ellipsis_to_short_text() {
        let body = Body::text("short".to_string());
        assert_eq!(body.__repr__(), r#"Body(type='text', content="short")"#);
    }

    #[test]
    fn test_repr_escapes_quotes_and_newlines() {
        let body = Body::text("a\"b\nc".to_string());
        let repr = body.__repr__();
        assert!(!repr.contains('\n'), "{repr}");
        assert!(repr.contains(r#"\"b\nc"#), "{repr}");
    }

    #[test]
    fn test_repr_truncates_long_text_on_char_boundary() {
        let body = Body::text("é".repeat(80));
        let repr = body.__repr__();
        assert!(repr.ends_with(", ...)"), "{repr}");
    }

    #[test]
    fn test_repr_handles_empty_text() {
        assert_eq!(
            Body::text(String::new()).__repr__(),
            r#"Body(type='text', content="")"#
        );
    }
}
