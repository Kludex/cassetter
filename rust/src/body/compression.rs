use std::io::Read;

use flate2::read::{DeflateDecoder, GzDecoder, ZlibDecoder};

/// Default ceiling on a decompressed body.
///
/// Without a ceiling a small compressed payload can expand without bound: a
/// 2 MB gzip of zeros reaches 512 MB, which pins gigabytes of RSS and stalls
/// the process for seconds with no catchable error.
pub const DEFAULT_MAX_DECOMPRESSED: usize = 256 * 1024 * 1024;

/// Decompress bytes based on the content-encoding header value.
pub fn decompress(data: &[u8], encoding: &str, limit: usize) -> Result<Vec<u8>, String> {
    match encoding.trim().to_lowercase().as_str() {
        "gzip" | "x-gzip" => read_capped(GzDecoder::new(data), limit, "gzip"),
        "deflate" => decompress_deflate(data, limit),
        "br" => read_capped(brotli::Decompressor::new(data, 4096), limit, "brotli"),
        "zstd" => {
            let decoder = zstd::stream::read::Decoder::new(data)
                .map_err(|e| format!("zstd decompression error: {e}"))?;
            read_capped(decoder, limit, "zstd")
        }
        "identity" | "" => {
            if data.len() > limit {
                return Err(over_limit("identity", limit));
            }
            Ok(data.to_vec())
        }
        other => Err(format!("unsupported content-encoding: {other}")),
    }
}

fn over_limit(what: &str, limit: usize) -> String {
    format!("{what} body exceeds the {limit} byte decompression limit")
}

/// Read a decoder to completion, refusing to allocate past `limit`.
fn read_capped<R: Read>(reader: R, limit: usize, what: &str) -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    // Read one byte past the limit so hitting it exactly is not an error.
    let read = reader
        .take(limit as u64 + 1)
        .read_to_end(&mut buf)
        .map_err(|e| format!("{what} decompression error: {e}"))?;
    if read > limit {
        return Err(over_limit(what, limit));
    }
    Ok(buf)
}

fn decompress_deflate(data: &[u8], limit: usize) -> Result<Vec<u8>, String> {
    // HTTP "deflate" is zlib-wrapped per RFC 9110, but some servers send
    // raw deflate streams; try zlib first, then fall back to raw.
    match read_capped(ZlibDecoder::new(data), limit, "deflate") {
        Ok(buf) => Ok(buf),
        Err(zlib_err) => {
            if zlib_err.contains("decompression limit") {
                return Err(zlib_err);
            }
            read_capped(DeflateDecoder::new(data), limit, "deflate")
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use flate2::write::GzEncoder;
    use flate2::Compression;

    use super::*;

    #[test]
    fn test_gzip_roundtrip() {
        let original = b"hello world";
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(original).unwrap();
        let compressed = encoder.finish().unwrap();

        let result = decompress(&compressed, "gzip", DEFAULT_MAX_DECOMPRESSED).unwrap();
        assert_eq!(result, original);
    }

    #[test]
    fn test_identity() {
        let data = b"unchanged";
        let result = decompress(data, "identity", DEFAULT_MAX_DECOMPRESSED).unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_gzip_bomb_is_capped() {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&vec![0u8; 4 * 1024 * 1024]).unwrap();
        let compressed = encoder.finish().unwrap();
        let err = decompress(&compressed, "gzip", 1024).unwrap_err();
        assert!(err.contains("decompression limit"), "{err}");
    }

    #[test]
    fn test_limit_boundary_is_inclusive() {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&[7u8; 100]).unwrap();
        let compressed = encoder.finish().unwrap();
        assert_eq!(decompress(&compressed, "gzip", 100).unwrap().len(), 100);
        assert!(decompress(&compressed, "gzip", 99).is_err());
    }

    #[test]
    fn test_unsupported_encoding() {
        let result = decompress(b"data", "compress", DEFAULT_MAX_DECOMPRESSED);
        assert!(result.is_err());
    }

    #[test]
    fn test_deflate_roundtrip() {
        use flate2::{write::ZlibEncoder, Compression};
        use std::io::Write;
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"deflated payload").unwrap();
        let compressed = encoder.finish().unwrap();
        assert_eq!(
            decompress(&compressed, "deflate", DEFAULT_MAX_DECOMPRESSED).unwrap(),
            b"deflated payload"
        );
    }

    #[test]
    fn test_raw_deflate_fallback() {
        use flate2::{write::DeflateEncoder, Compression};
        use std::io::Write;
        let mut encoder = DeflateEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"raw deflate").unwrap();
        let compressed = encoder.finish().unwrap();
        assert_eq!(
            decompress(&compressed, "deflate", DEFAULT_MAX_DECOMPRESSED).unwrap(),
            b"raw deflate"
        );
    }
}
