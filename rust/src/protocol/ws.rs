use std::collections::HashMap;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use super::http::Body;

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsFrame {
    #[pyo3(get, set)]
    pub direction: String,
    #[pyo3(get, set)]
    pub frame_type: String,
    pub body: Body,
    #[pyo3(get, set)]
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

    #[setter]
    fn set_body(&mut self, body: Body) {
        self.body = body;
    }

    fn __repr__(&self) -> String {
        format!(
            "WsFrame(direction='{}', frame_type='{}', offset_ms={})",
            self.direction, self.frame_type, self.offset_ms
        )
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsInteraction {
    #[pyo3(get, set)]
    pub uri: String,
    #[pyo3(get, set)]
    pub headers: HashMap<String, Vec<String>>,
    pub frames: Vec<WsFrame>,
    #[pyo3(get, set)]
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

    #[setter]
    fn set_frames(&mut self, frames: Vec<WsFrame>) {
        self.frames = frames;
    }

    fn __repr__(&self) -> String {
        format!(
            "WsInteraction(uri='{}', frames={})",
            self.uri,
            self.frames.len()
        )
    }
}
