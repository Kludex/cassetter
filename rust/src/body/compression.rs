use std::io::Read;

use flate2::read::{DeflateDecoder, GzDecoder, ZlibDecoder};

/// Decompress bytes based on the content-encoding header value.
pub fn decompress(data: &[u8], encoding: &str) -> Result<Vec<u8>, String> {
    match encoding.trim().to_lowercase().as_str() {
        "gzip" | "x-gzip" => decompress_gzip(data),
        "deflate" => decompress_deflate(data),
        "br" => decompress_brotli(data),
        "zstd" => decompress_zstd(data),
        "identity" | "" => Ok(data.to_vec()),
        other => Err(format!("unsupported content-encoding: {other}")),
    }
}

fn decompress_gzip(data: &[u8]) -> Result<Vec<u8>, String> {
    let mut decoder = GzDecoder::new(data);
    let mut buf = Vec::new();
    decoder
        .read_to_end(&mut buf)
        .map_err(|e| format!("gzip decompression error: {e}"))?;
    Ok(buf)
}

fn decompress_deflate(data: &[u8]) -> Result<Vec<u8>, String> {
    // HTTP "deflate" is zlib-wrapped per RFC 9110, but some servers send
    // raw deflate streams; try zlib first, then fall back to raw.
    let mut buf = Vec::new();
    if ZlibDecoder::new(data).read_to_end(&mut buf).is_ok() {
        return Ok(buf);
    }
    let mut buf = Vec::new();
    DeflateDecoder::new(data)
        .read_to_end(&mut buf)
        .map_err(|e| format!("deflate decompression error: {e}"))?;
    Ok(buf)
}

fn decompress_brotli(data: &[u8]) -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    brotli::BrotliDecompress(&mut &data[..], &mut buf)
        .map_err(|e| format!("brotli decompression error: {e}"))?;
    Ok(buf)
}

fn decompress_zstd(data: &[u8]) -> Result<Vec<u8>, String> {
    zstd::stream::decode_all(data).map_err(|e| format!("zstd decompression error: {e}"))
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

        let result = decompress(&compressed, "gzip").unwrap();
        assert_eq!(result, original);
    }

    #[test]
    fn test_identity() {
        let data = b"unchanged";
        let result = decompress(data, "identity").unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_unsupported_encoding() {
        let result = decompress(b"data", "compress");
        assert!(result.is_err());
    }

    #[test]
    fn test_deflate_roundtrip() {
        use flate2::{write::ZlibEncoder, Compression};
        use std::io::Write;
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"deflated payload").unwrap();
        let compressed = encoder.finish().unwrap();
        assert_eq!(decompress(&compressed, "deflate").unwrap(), b"deflated payload");
    }

    #[test]
    fn test_raw_deflate_fallback() {
        use flate2::{write::DeflateEncoder, Compression};
        use std::io::Write;
        let mut encoder = DeflateEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"raw deflate").unwrap();
        let compressed = encoder.finish().unwrap();
        assert_eq!(decompress(&compressed, "deflate").unwrap(), b"raw deflate");
    }
}
