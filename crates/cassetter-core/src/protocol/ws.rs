use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::http::Body;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsFrame {
    pub direction: String,
    pub frame_type: String,
    pub body: Body,
    pub offset_ms: u64,
}

impl WsFrame {
    pub fn new(direction: String, frame_type: String, body: Body, offset_ms: u64) -> Self {
        WsFrame {
            direction,
            frame_type,
            body,
            offset_ms,
        }
    }

    pub fn describe(&self) -> String {
        format!(
            "WsFrame(direction={:?}, frame_type={:?}, offset_ms={})",
            self.direction, self.frame_type, self.offset_ms
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WsInteraction {
    pub uri: String,
    pub headers: HashMap<String, Vec<String>>,
    pub frames: Vec<WsFrame>,
    pub recorded_at: String,
}

impl WsInteraction {
    pub fn new(
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

    pub fn describe(&self) -> String {
        format!(
            "WsInteraction(uri={:?}, frames={})",
            self.uri,
            self.frames.len()
        )
    }
}
