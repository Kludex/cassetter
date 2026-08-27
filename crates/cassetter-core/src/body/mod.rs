pub mod compression;
pub mod hex;
pub mod json;
pub mod unicode;

use crate::protocol::http::Body;
use crate::{CassetteError, Result};

/// Process raw response bytes into a structured Body.
///
/// Handles decompression (gzip, brotli, zstd), JSON detection/parsing, and
/// Unicode normalization.
///
/// `max_decompressed` caps the decompressed size; pass
/// [`compression::DEFAULT_MAX_DECOMPRESSED`] for the default.
///
/// This is pure and can be slow on a large body, so bindings should release
/// any interpreter lock around it.
pub fn process_body(
    raw_bytes: Vec<u8>,
    content_type: Option<&str>,
    content_encoding: Option<&str>,
    max_decompressed: usize,
) -> Result<Body> {
    if raw_bytes.is_empty() {
        return Ok(Body::none());
    }

    // Decompress if needed
    let decompressed = if let Some(encoding) = content_encoding {
        compression::decompress(&raw_bytes, encoding, max_decompressed)
            .map_err(|e| CassetteError::Value(format!("decompression failed: {e}")))?
    } else {
        raw_bytes
    };

    // Determine if this is JSON
    let is_json = content_type
        .map(json::is_json_content_type)
        .unwrap_or(false);

    if is_json {
        if let Ok(value) = json::parse_json(&decompressed) {
            return Ok(Body::json(value));
        }
        // Fall through to text if JSON parsing fails
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
