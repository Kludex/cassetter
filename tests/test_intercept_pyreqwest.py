from __future__ import annotations

import json
import os
from unittest.mock import patch

import pyreqwest_impersonate as pri
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._pyreqwest import (
    PyreqwestInterceptor,
    ReplayResponse,
    build_replay_response,
    extract_body,
    extract_headers,
)


def _preload_cassette(path: str) -> None:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/api"),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"data": "hello"})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)


def test_interceptor_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        client = pri.Client()
        response = client.get("https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}


def test_interceptor_replay_via_request_method(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        client = pri.Client()
        response = client.request("GET", "https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}


def test_interceptor_no_match_cant_record(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        client = pri.Client()
        with pytest.raises(NoMatchError):
            client.delete("https://example.com/unknown")


def test_interceptor_install_uninstall() -> None:
    interceptor = PyreqwestInterceptor()
    original_get = pri.Client.get

    interceptor.install()
    assert pri.Client.get is not original_get

    interceptor.uninstall()
    assert pri.Client.get is original_get


def testextract_headers_none() -> None:
    assert extract_headers(None) == {}


def testextract_headers_dict() -> None:
    headers = {"Content-Type": "application/json", "Accept": "text/html"}
    result = extract_headers(headers)
    assert result == {"content-type": ["application/json"], "accept": ["text/html"]}


def testextract_body_content_bytes() -> None:
    assert extract_body(content=b"raw", data=None, json_payload=None) == b"raw"


def testextract_body_data_string() -> None:
    assert extract_body(content=None, data="form=data", json_payload=None) == b"form=data"


def testextract_body_json_payload() -> None:
    result = extract_body(content=None, data=None, json_payload={"key": "val"})
    assert json.loads(result) == {"key": "val"}  # type: ignore[arg-type]


def testextract_body_none() -> None:
    assert extract_body(content=None, data=None, json_payload=None) is None


def test_replay_response_text() -> None:
    r = ReplayResponse(status_code=200, headers={}, content=b"hello", url="https://x.com")
    assert r.text == "hello"
    assert r.text_plain == "hello"
    assert r.text_markdown == "hello"


def test_replay_response_json() -> None:
    r = ReplayResponse(status_code=200, headers={}, content=b'{"a": 1}', url="https://x.com")
    assert r.json() == {"a": 1}


def testbuild_replay_response_json_body() -> None:
    resp = build_replay_response(
        "https://example.com",
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert resp.json() == {"key": "value"}
    assert resp.status_code == 200


def testbuild_replay_response_text_body() -> None:
    resp = build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert resp.text == "hello world"


def testbuild_replay_response_binary_body() -> None:
    resp = build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert resp.content == b"\x00\x01\x02"


def testbuild_replay_response_none_body() -> None:
    resp = build_replay_response(
        "https://example.com",
        HttpResponse(200, body=Body("none")),
    )
    assert resp.content == b""


def test_record_uses_request_url_not_response_url(tmp_path: object) -> None:
    """Recording must store the request URL: responses carry post-redirect URLs
    that would never match on replay."""

    path = os.path.join(str(tmp_path), "redirect.yaml")

    class FakeResponse:
        url = "https://example.com/redirected-target"
        status_code = 200
        headers = {"content-type": "application/json", "content-encoding": "gzip"}
        content = b'{"ok": true}'

    def fake_get(self: object, url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse()

    with patch.object(pri.Client, "get", fake_get):
        with use_cassette(path, record_mode="all", intercept=["pyreqwest"]) as cassette:
            client = pri.Client()
            client.get("https://example.com/original")

            recorded = cassette.interactions[0]
            assert recorded.request.uri == "https://example.com/original"
            # decompressed content is recorded, so the encoding header is dropped
            assert "content-encoding" not in recorded.response.headers

    # Replay with the original request URL must match
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        client = pri.Client()
        response = client.get("https://example.com/original")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
