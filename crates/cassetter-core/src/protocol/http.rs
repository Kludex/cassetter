use std::collections::HashMap;

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

impl BodyContent {
    /// The type discriminator as it appears in the cassette file.
    pub fn type_name(&self) -> &'static str {
        match self {
            BodyContent::Json(_) => "json",
            BodyContent::Text(_) => "text",
            BodyContent::Binary(_) => "binary",
            BodyContent::None => "none",
        }
    }
}

/// Trim a string to at most `max` characters, on a character boundary.
fn preview(s: &str, max: usize) -> (&str, bool) {
    match s.char_indices().nth(max) {
        Some((idx, _)) => (&s[..idx], true),
        None => (s, false),
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Body {
    #[serde(flatten)]
    pub inner: BodyContent,
}

impl Body {
    /// An empty body.
    pub fn none() -> Self {
        Body {
            inner: BodyContent::None,
        }
    }

    /// A body holding parsed JSON.
    pub fn json(value: serde_json::Value) -> Self {
        Body {
            inner: BodyContent::Json(value),
        }
    }

    /// A body holding text.
    pub fn text(s: String) -> Self {
        Body {
            inner: BodyContent::Text(s),
        }
    }

    /// A body holding raw bytes.
    pub fn binary(b: Vec<u8>) -> Self {
        Body {
            inner: BodyContent::Binary(b),
        }
    }

    /// Build a body from an already-constructed content value.
    pub fn from_content(inner: BodyContent) -> Self {
        Body { inner }
    }

    /// Short human-readable summary. Bindings surface this as `__repr__`,
    /// `toString`, and the like.
    pub fn describe(&self) -> String {
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

impl Default for Body {
    /// The empty body.
    fn default() -> Self {
        Body::none()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpRequest {
    pub method: String,
    pub uri: String,
    pub headers: HashMap<String, Vec<String>>,
    pub body: Body,
}

impl HttpRequest {
    /// Build a HttpRequest.
    pub fn new(
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

    /// A short, readable rendering for a binding to surface.
    pub fn describe(&self) -> String {
        format!("HttpRequest(method={:?}, uri={:?})", self.method, self.uri)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpResponse {
    pub status: u16,
    pub headers: HashMap<String, Vec<String>>,
    pub body: Body,
}

impl HttpResponse {
    /// Build a HttpResponse.
    pub fn new(
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

    /// A short, readable rendering for a binding to surface.
    pub fn describe(&self) -> String {
        format!("HttpResponse(status={})", self.status)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HttpInteraction {
    pub request: HttpRequest,
    pub response: HttpResponse,
    pub recorded_at: String,
}

impl HttpInteraction {
    /// Build a HttpInteraction.
    pub fn new(request: HttpRequest, response: HttpResponse, recorded_at: String) -> Self {
        HttpInteraction {
            request,
            response,
            recorded_at,
        }
    }

    /// A short, readable rendering for a binding to surface.
    pub fn describe(&self) -> String {
        format!(
            "HttpInteraction(request={}, response={})",
            self.request.describe(),
            self.response.describe()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_body_uses_one_type_discriminator() {
        let bodies = [
            Body::json(serde_json::json!({"ok": true})),
            Body::text("hello".to_string()),
            Body::binary(vec![0, 1]),
            Body::none(),
        ];

        for body in bodies {
            let serialized = serde_json::to_string(&body).unwrap();
            assert_eq!(serialized.matches(r#""type""#).count(), 1, "{serialized}");
            assert_eq!(serde_json::from_str::<Body>(&serialized).unwrap(), body);
        }
    }

    #[test]
    fn test_repr_does_not_append_ellipsis_to_short_text() {
        let body = Body::text("short".to_string());
        assert_eq!(body.describe(), r#"Body(type='text', content="short")"#);
    }

    #[test]
    fn test_repr_escapes_quotes_and_newlines() {
        let body = Body::text("a\"b\nc".to_string());
        let repr = body.describe();
        assert!(!repr.contains('\n'), "{repr}");
        assert!(repr.contains(r#"\"b\nc"#), "{repr}");
    }

    #[test]
    fn test_repr_truncates_long_text_on_char_boundary() {
        let body = Body::text("é".repeat(80));
        let repr = body.describe();
        assert!(repr.ends_with(", ...)"), "{repr}");
    }

    #[test]
    fn test_repr_handles_empty_text() {
        assert_eq!(
            Body::text(String::new()).describe(),
            r#"Body(type='text', content="")"#
        );
    }
}
