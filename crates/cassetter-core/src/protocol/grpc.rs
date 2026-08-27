use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::http::Body;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcRequest {
    pub method: String,
    pub metadata: HashMap<String, Vec<String>>,
    pub body: Body,
}

impl GrpcRequest {
    pub fn new(
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

    pub fn describe(&self) -> String {
        format!("GrpcRequest(method={:?})", self.method)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcResponse {
    pub status_code: u32,
    pub status_message: String,
    pub metadata: HashMap<String, Vec<String>>,
    pub body: Body,
}

impl GrpcResponse {
    pub fn new(
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

    pub fn describe(&self) -> String {
        format!(
            "GrpcResponse(status_code={}, status_message={:?})",
            self.status_code, self.status_message
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GrpcInteraction {
    pub request: GrpcRequest,
    pub response: GrpcResponse,
    /// Optional human-readable protobuf representation for debugging.
    pub json_debug: Option<serde_json::Value>,
    pub recorded_at: String,
}

impl GrpcInteraction {
    pub fn new(
        request: GrpcRequest,
        response: GrpcResponse,
        recorded_at: String,
        json_debug: Option<serde_json::Value>,
    ) -> Self {
        GrpcInteraction {
            request,
            response,
            json_debug,
            recorded_at,
        }
    }

    pub fn describe(&self) -> String {
        format!(
            "GrpcInteraction(request={}, response={})",
            self.request.describe(),
            self.response.describe()
        )
    }
}
