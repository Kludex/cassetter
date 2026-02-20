from __future__ import annotations

import gzip

import pytest

from vcr_but_better._core import Body, process_body


class TestBody:
    def test_json_body(self) -> None:
        body = Body("json", {"key": "value"})
        assert body.body_type == "json"
        assert body.content == {"key": "value"}

    def test_text_body(self) -> None:
        body = Body("text", "hello world")
        assert body.body_type == "text"
        assert body.content == "hello world"

    def test_binary_body(self) -> None:
        body = Body("binary", b"\x00\x01\x02")
        assert body.body_type == "binary"
        assert body.content == b"\x00\x01\x02"

    def test_none_body(self) -> None:
        body = Body("none")
        assert body.body_type == "none"
        assert body.content is None

    def test_invalid_body_type(self) -> None:
        with pytest.raises(ValueError, match="unknown body type"):
            Body("invalid", "data")


class TestProcessBody:
    def test_empty_bytes(self) -> None:
        body = process_body(b"")
        assert body.body_type == "none"

    def test_json_content_type(self) -> None:
        body = process_body(b'{"key": "value"}', "application/json")
        assert body.body_type == "json"
        assert body.content == {"key": "value"}

    def test_text_content_type(self) -> None:
        body = process_body(b"hello world", "text/plain")
        assert body.body_type == "text"
        assert body.content == "hello world"

    def test_gzip_decompression(self) -> None:
        original = b'{"decompressed": true}'
        compressed = gzip.compress(original)
        body = process_body(compressed, "application/json", "gzip")
        assert body.body_type == "json"
        assert body.content == {"decompressed": True}

    def test_auto_detect_json(self) -> None:
        body = process_body(b"[1, 2, 3]")
        assert body.body_type == "json"
        assert body.content == [1, 2, 3]

    def test_binary_fallback(self) -> None:
        body = process_body(b"\x00\x01\xff\xfe", "application/octet-stream")
        assert body.body_type == "binary"

    def test_unicode_normalization(self) -> None:
        # Smart quotes should be preserved (only NFC normalization applied)
        text = "\u201chello\u201d".encode()
        body = process_body(text, "text/plain")
        assert body.body_type == "text"
        assert body.content == "\u201chello\u201d"
