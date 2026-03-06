from __future__ import annotations

import json
import os

import pyreqwest_impersonate as pri
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.intercept._pyreqwest import (
    PyreqwestInterceptor,
    _build_replay_response,
    _extract_body,
    _extract_headers,
    _ReplayResponse,
)
from cassetter.recording import RecordMode


def _preload_cassette(path: str) -> Cassette:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/api"),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"data": "hello"})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    return cassette


def test_interceptor_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = PyreqwestInterceptor()
    interceptor.install(cassette)

    try:
        client = pri.Client()
        response = client.get("https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}
    finally:
        interceptor.uninstall()


def test_interceptor_replay_via_request_method(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = PyreqwestInterceptor()
    interceptor.install(cassette)

    try:
        client = pri.Client()
        response = client.request("GET", "https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}
    finally:
        interceptor.uninstall()


def test_interceptor_no_match_cant_record(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = PyreqwestInterceptor()
    interceptor.install(cassette)

    try:
        client = pri.Client()
        with pytest.raises(NoMatchError):
            client.delete("https://example.com/unknown")
    finally:
        interceptor.uninstall()


def test_interceptor_install_uninstall() -> None:
    interceptor = PyreqwestInterceptor()
    original_get = pri.Client.get
    cassette = Cassette("/nonexistent", record_mode=RecordMode.NONE)
    cassette.load()

    interceptor.install(cassette)
    assert pri.Client.get is not original_get

    interceptor.uninstall()
    assert pri.Client.get is original_get


def test_extract_headers_none() -> None:
    assert _extract_headers(None) == {}


def test_extract_headers_dict() -> None:
    headers = {"Content-Type": "application/json", "Accept": "text/html"}
    result = _extract_headers(headers)
    assert result == {"content-type": ["application/json"], "accept": ["text/html"]}


def test_extract_body_content_bytes() -> None:
    assert _extract_body(content=b"raw", data=None, json_payload=None) == b"raw"


def test_extract_body_data_string() -> None:
    assert _extract_body(content=None, data="form=data", json_payload=None) == b"form=data"


def test_extract_body_json_payload() -> None:
    result = _extract_body(content=None, data=None, json_payload={"key": "val"})
    assert json.loads(result) == {"key": "val"}  # type: ignore[arg-type]


def test_extract_body_none() -> None:
    assert _extract_body(content=None, data=None, json_payload=None) is None


def test_replay_response_text() -> None:
    r = _ReplayResponse(status_code=200, headers={}, content=b"hello", url="https://x.com")
    assert r.text == "hello"
    assert r.text_plain == "hello"
    assert r.text_markdown == "hello"


def test_replay_response_json() -> None:
    r = _ReplayResponse(status_code=200, headers={}, content=b'{"a": 1}', url="https://x.com")
    assert r.json() == {"a": 1}


def test_build_replay_response_json_body() -> None:
    resp = _build_replay_response(
        "https://example.com",
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert resp.json() == {"key": "value"}
    assert resp.status_code == 200


def test_build_replay_response_text_body() -> None:
    resp = _build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert resp.text == "hello world"


def test_build_replay_response_binary_body() -> None:
    resp = _build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert resp.content == b"\x00\x01\x02"


def test_build_replay_response_none_body() -> None:
    resp = _build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("none")),
    )
    assert resp.content == b""
