pub mod compression;
pub mod json;
pub mod unicode;

use pyo3::prelude::*;

use crate::protocol::http::Body;

/// Process raw response bytes into a structured Body.
///
/// Handles decompression (gzip, brotli, zstd), JSON detection/parsing,
/// and Unicode normalization.
#[pyfunction]
#[pyo3(signature = (raw_bytes, content_type=None, content_encoding=None))]
pub fn process_body(
    raw_bytes: Vec<u8>,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> PyResult<Body> {
    if raw_bytes.is_empty() {
        return Ok(Body::none());
    }

    // Decompress if needed
    let decompressed = if let Some(ref encoding) = content_encoding {
        compression::decompress(&raw_bytes, encoding).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("decompression failed: {e}"))
        })?
    } else {
        raw_bytes
    };

    // Determine if this is JSON
    let is_json = content_type
        .as_deref()
        .map(|ct| json::is_json_content_type(ct))
        .unwrap_or(false);

    if is_json {
        match json::parse_json(&decompressed) {
            Ok(value) => return Ok(Body::json(value)),
            Err(_) => {
                // Fall through to text if JSON parsing fails
            }
        }
    }

    // Try as UTF-8 text
    match String::from_utf8(decompressed.clone()) {
        Ok(text) => {
            let normalized = unicode::normalize_text(&text);
            // If no explicit content type, try to detect JSON
            if content_type.is_none() {
                if let Ok(value) = json::parse_json(normalized.as_bytes()) {
                    return Ok(Body::json(value));
                }
            }
            Ok(Body::text(normalized))
        }
        Err(_) => Ok(Body::binary(decompressed)),
    }
}
