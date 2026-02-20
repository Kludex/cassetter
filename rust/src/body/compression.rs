use std::io::Read;

use flate2::read::GzDecoder;

/// Decompress bytes based on the content-encoding header value.
pub fn decompress(data: &[u8], encoding: &str) -> Result<Vec<u8>, String> {
    match encoding.trim().to_lowercase().as_str() {
        "gzip" | "x-gzip" => decompress_gzip(data),
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
        let result = decompress(b"data", "deflate");
        assert!(result.is_err());
    }
}
