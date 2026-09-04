//! Hex encoding/decoding for binary cassette bodies.

/// Encode bytes as a lowercase hex string.
pub fn encode(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}

/// Decode a lowercase/uppercase hex string into bytes.
pub fn decode(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd-length hex string".to_string());
    }
    if !s.is_ascii() {
        return Err("non-ASCII hex string".to_string());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_roundtrip() {
        let data = vec![0u8, 1, 255, 16, 128];
        assert_eq!(decode(&encode(&data)).unwrap(), data);
    }

    #[test]
    fn test_odd_length_rejected() {
        assert!(decode("abc").is_err());
    }

    #[test]
    fn test_non_ascii_rejected() {
        assert!(decode("ab€f").is_err());
    }
}
