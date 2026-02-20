use unicode_normalization::UnicodeNormalization;

/// Normalize text: NFC normalization + smart quote replacement.
pub fn normalize_text(text: &str) -> String {
    let normalized: String = text.nfc().collect();
    replace_smart_quotes(&normalized)
}

/// Replace smart/curly quotes with their ASCII equivalents.
fn replace_smart_quotes(text: &str) -> String {
    text.replace('\u{2018}', "'") // left single quote
        .replace('\u{2019}', "'") // right single quote
        .replace('\u{201C}', "\"") // left double quote
        .replace('\u{201D}', "\"") // right double quote
        .replace('\u{2013}', "-") // en dash
        .replace('\u{2014}', "-") // em dash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_smart_quotes() {
        let input = "\u{201C}hello\u{201D} \u{2018}world\u{2019}";
        assert_eq!(normalize_text(input), "\"hello\" 'world'");
    }

    #[test]
    fn test_dashes() {
        assert_eq!(normalize_text("a\u{2013}b\u{2014}c"), "a-b-c");
    }

    #[test]
    fn test_plain_text_unchanged() {
        assert_eq!(normalize_text("hello world"), "hello world");
    }
}
