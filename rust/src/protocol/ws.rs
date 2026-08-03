use std::collections::HashMap;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use super::http::Body;

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsFrame {
    #[pyo3(get)]
    pub direction: String,
    #[pyo3(get)]
    pub frame_type: String,
    pub body: Body,
    #[pyo3(get)]
    pub offset_ms: u64,
}

#[pymethods]
impl WsFrame {
    #[new]
    #[pyo3(signature = (direction, frame_type, body, offset_ms=0))]
    fn new(direction: String, frame_type: String, body: Body, offset_ms: u64) -> Self {
        WsFrame {
            direction,
            frame_type,
            body,
            offset_ms,
        }
    }

    #[getter]
    fn body(&self) -> Body {
        self.body.clone()
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
        WsFrame {
            direction: direction.unwrap_or_else(|| self.direction.clone()),
            frame_type: frame_type.unwrap_or_else(|| self.frame_type.clone()),
            body: body.unwrap_or_else(|| self.body.clone()),
            offset_ms: offset_ms.unwrap_or(self.offset_ms),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "WsFrame(direction={:?}, frame_type={:?}, offset_ms={})",
            self.direction, self.frame_type, self.offset_ms
        )
    }
}

#[pyclass(frozen, eq, from_py_object, module = "cassetter._core")]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsInteraction {
    #[pyo3(get)]
    pub uri: String,
    #[pyo3(get)]
    pub headers: HashMap<String, Vec<String>>,
    pub frames: Vec<WsFrame>,
    #[pyo3(get)]
    pub recorded_at: String,
}

#[pymethods]
impl WsInteraction {
    #[new]
    #[pyo3(signature = (uri, headers=None, frames=None, recorded_at=None))]
    fn new(
        uri: String,
        headers: Option<HashMap<String, Vec<String>>>,
        frames: Option<Vec<WsFrame>>,
        recorded_at: Option<String>,
    ) -> Self {
        WsInteraction {
            uri,
            headers: headers.unwrap_or_default(),
            frames: frames.unwrap_or_default(),
            recorded_at: recorded_at.unwrap_or_default(),
        }
    }

    #[getter]
    fn frames(&self) -> Vec<WsFrame> {
        self.frames.clone()
    }

    /// Return a copy with the given fields replaced.
    #[pyo3(signature = (*, uri=None, headers=None, frames=None, recorded_at=None))]
    fn replace(
        &self,
        uri: Option<String>,
        headers: Option<HashMap<String, Vec<String>>>,
        frames: Option<Vec<WsFrame>>,
        recorded_at: Option<String>,
    ) -> Self {
        WsInteraction {
            uri: uri.unwrap_or_else(|| self.uri.clone()),
            headers: headers.unwrap_or_else(|| self.headers.clone()),
            frames: frames.unwrap_or_else(|| self.frames.clone()),
            recorded_at: recorded_at.unwrap_or_else(|| self.recorded_at.clone()),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "WsInteraction(uri={:?}, frames={})",
            self.uri,
            self.frames.len()
        )
    }
}
