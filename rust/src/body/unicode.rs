use unicode_normalization::UnicodeNormalization;

/// Normalize text to NFC form for consistent matching.
///
/// Only applies Unicode NFC normalization. Does NOT replace smart quotes
/// or other characters, as that would corrupt embedded JSON (e.g. in SSE
/// responses where curly quotes are valid unescaped but ASCII quotes are not).
pub fn normalize_text(text: &str) -> String {
    text.nfc().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_nfc_normalization() {
        // e + combining acute -> precomposed e-acute
        let input = "caf\u{0065}\u{0301}";
        assert_eq!(normalize_text(input), "caf\u{00E9}");
    }

    #[test]
    fn test_smart_quotes_preserved() {
        // Smart quotes must NOT be replaced - they are valid in JSON strings
        // and replacing them with ASCII quotes would break embedded JSON
        let input = "\u{201C}hello\u{201D} \u{2018}world\u{2019}";
        assert_eq!(
            normalize_text(input),
            "\u{201C}hello\u{201D} \u{2018}world\u{2019}"
        );
    }

    #[test]
    fn test_plain_text_unchanged() {
        assert_eq!(normalize_text("hello world"), "hello world");
    }
}
