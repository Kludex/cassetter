pub mod compression;
pub mod hex;
pub mod json;
pub mod unicode;

use pyo3::prelude::*;

use crate::protocol::http::Body;

/// Process raw response bytes into a structured Body.
///
/// Handles decompression (gzip, brotli, zstd), JSON detection/parsing,
/// and Unicode normalization.
///
/// `max_decompressed` caps the decompressed size; it defaults to
/// [`compression::DEFAULT_MAX_DECOMPRESSED`].
///
/// The GIL is released for the whole pipeline - decompression of a large body
/// takes seconds, and holding the GIL through it freezes the interpreter.
#[pyfunction]
#[pyo3(signature = (raw_bytes, content_type=None, content_encoding=None, max_decompressed=None))]
pub fn process_body(
    py: Python<'_>,
    raw_bytes: Vec<u8>,
    content_type: Option<String>,
    content_encoding: Option<String>,
    max_decompressed: Option<usize>,
) -> PyResult<Body> {
    py.detach(|| {
        process_body_impl(
            raw_bytes,
            content_type.as_deref(),
            content_encoding.as_deref(),
            max_decompressed.unwrap_or(compression::DEFAULT_MAX_DECOMPRESSED),
        )
    })
}

pub fn process_body_impl(
    raw_bytes: Vec<u8>,
    content_type: Option<&str>,
    content_encoding: Option<&str>,
    max_decompressed: usize,
) -> PyResult<Body> {
    if raw_bytes.is_empty() {
        return Ok(Body::none());
    }

    // Decompress if needed
    let decompressed = if let Some(encoding) = content_encoding {
        compression::decompress(&raw_bytes, encoding, max_decompressed).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("decompression failed: {e}"))
        })?
    } else {
        raw_bytes
    };

    // Determine if this is JSON
    let is_json = content_type
        .map(json::is_json_content_type)
        .unwrap_or(false);

    if is_json {
        match json::parse_json(&decompressed) {
            Ok(value) => return Ok(Body::json(value)),
            Err(_) => {
                // Fall through to text if JSON parsing fails
            }
        }
    }

    // Try as UTF-8 text, handing the buffer back on failure rather than
    // keeping a second copy alive for the binary case.
    match String::from_utf8(decompressed) {
        Ok(text) => {
            let normalized = unicode::normalize_text(text);
            // If no explicit content type, try to detect JSON
            if content_type.is_none() {
                if let Ok(value) = json::parse_json(normalized.as_bytes()) {
                    return Ok(Body::json(value));
                }
            }
            Ok(Body::text(normalized))
        }
        Err(e) => Ok(Body::binary(e.into_bytes())),
    }
}
