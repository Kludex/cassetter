from __future__ import annotations

import gzip

import pytest

from cassetter._core import Body, process_body


def test_body_json() -> None:
    body = Body("json", {"key": "value"})
    assert body.body_type == "json"
    assert body.content == {"key": "value"}


def test_body_text() -> None:
    body = Body("text", "hello world")
    assert body.body_type == "text"
    assert body.content == "hello world"


def test_body_binary() -> None:
    body = Body("binary", b"\x00\x01\x02")
    assert body.body_type == "binary"
    assert body.content == b"\x00\x01\x02"


def test_body_none() -> None:
    body = Body("none")
    assert body.body_type == "none"
    assert body.content is None


def test_body_invalid_type() -> None:
    with pytest.raises(ValueError, match="unknown body type"):
        Body("invalid", "data")  # type: ignore[arg-type]


def test_process_body_empty_bytes() -> None:
    body = process_body(b"")
    assert body.body_type == "none"


def test_process_body_json_content_type() -> None:
    body = process_body(b'{"key": "value"}', "application/json")
    assert body.body_type == "json"
    assert body.content == {"key": "value"}


def test_process_body_text_content_type() -> None:
    body = process_body(b"hello world", "text/plain")
    assert body.body_type == "text"
    assert body.content == "hello world"


def test_process_body_gzip_decompression() -> None:
    original = b'{"decompressed": true}'
    compressed = gzip.compress(original)
    body = process_body(compressed, "application/json", "gzip")
    assert body.body_type == "json"
    assert body.content == {"decompressed": True}


def test_process_body_auto_detect_json() -> None:
    body = process_body(b"[1, 2, 3]")
    assert body.body_type == "json"
    assert body.content == [1, 2, 3]


def test_process_body_binary_fallback() -> None:
    body = process_body(b"\x00\x01\xff\xfe", "application/octet-stream")
    assert body.body_type == "binary"


def test_process_body_unicode_normalization() -> None:
    # Smart quotes should be preserved (only NFC normalization applied)
    text = "\u201chello\u201d".encode()
    body = process_body(text, "text/plain")
    assert body.body_type == "text"
    assert body.content == "\u201chello\u201d"
