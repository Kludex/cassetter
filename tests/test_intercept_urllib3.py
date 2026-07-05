from __future__ import annotations

import io
import os
from unittest.mock import MagicMock

import pytest
import requests
import urllib3
import urllib3.connectionpool
import urllib3.response

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._urllib3 import (
    Urllib3Interceptor,
    build_urllib3_response,
    extract_headers,
    is_default_port,
    reconstruct_url,
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


def test_replay_via_urllib3(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["urllib3"]):
        http = urllib3.PoolManager()
        response = http.request("GET", "https://example.com/api")
        assert response.status == 200
        assert response.json() == {"data": "hello"}


def test_replay_via_requests(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["urllib3"]):
        response = requests.get("https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}


def test_replay_with_mismatched_content_length(tmp_path: object) -> None:
    """Replaying a cassette whose stored content-length differs from the re-serialized body must not raise."""
    path = os.path.join(str(tmp_path), "test.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("POST", "https://api.example.com/invoke"),
            response=HttpResponse(
                200,
                {"content-type": ["application/json"], "content-length": ["999"]},
                Body("json", {"modelId": "test", "output": {"message": {"content": [{"text": "hi"}]}}}),
            ),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)

    with use_cassette(path, record_mode="none", intercept=["urllib3"]):
        http = urllib3.PoolManager()
        response = http.request("POST", "https://api.example.com/invoke")
        assert response.status == 200
        body = response.json()
        assert body["output"]["message"]["content"][0]["text"] == "hi"


def test_record_urllib3(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")

    fake_response = urllib3.response.HTTPResponse(
        body=io.BytesIO(b'{"recorded": true}'),
        headers={"content-type": "application/json"},
        status=201,
        preload_content=False,
    )
    fake_response._body = b'{"recorded": true}'

    monkeypatch.setattr(
        urllib3.connectionpool.HTTPConnectionPool,
        "urlopen",
        lambda self, method, url, **kwargs: fake_response,
    )

    with use_cassette(path, record_mode="all", intercept=["urllib3"]) as cassette:
        http = urllib3.PoolManager()
        response = http.request("GET", "https://example.com/new-endpoint")
        assert response.status == 201
        assert len(cassette.interactions) == 1

    monkeypatch.undo()


def test_no_match_raises_error(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["urllib3"]):
        with pytest.raises(NoMatchError):
            http = urllib3.PoolManager()
            http.request("DELETE", "https://example.com/unknown", retries=False)


def test_install_uninstall_restores_original() -> None:
    interceptor = Urllib3Interceptor()
    original = urllib3.connectionpool.HTTPConnectionPool.urlopen

    interceptor.install()
    assert urllib3.connectionpool.HTTPConnectionPool.urlopen is not original

    interceptor.uninstall()
    assert urllib3.connectionpool.HTTPConnectionPool.urlopen is original


def test_uninstall_without_install() -> None:
    interceptor = Urllib3Interceptor()
    interceptor.uninstall()


def testreconstruct_url_https_default_port() -> None:
    pool = MagicMock()
    pool.scheme = "https"
    pool.host = "example.com"
    pool.port = 443
    assert reconstruct_url(pool, "/api") == "https://example.com/api"


def testreconstruct_url_http_default_port() -> None:
    pool = MagicMock()
    pool.scheme = "http"
    pool.host = "example.com"
    pool.port = 80
    assert reconstruct_url(pool, "/api") == "http://example.com/api"


def testreconstruct_url_custom_port() -> None:
    pool = MagicMock()
    pool.scheme = "https"
    pool.host = "example.com"
    pool.port = 8443
    assert reconstruct_url(pool, "/api") == "https://example.com:8443/api"


def testreconstruct_url_no_port() -> None:
    pool = MagicMock()
    pool.scheme = "https"
    pool.host = "example.com"
    pool.port = None
    assert reconstruct_url(pool, "/api?q=1") == "https://example.com/api?q=1"


def testis_default_port_http_80() -> None:
    assert is_default_port("http", 80) is True


def testis_default_port_https_443() -> None:
    assert is_default_port("https", 443) is True


def testis_default_port_non_default() -> None:
    assert is_default_port("https", 8080) is False


def testextract_headers_none() -> None:
    assert extract_headers(None) == {}


def testextract_headers_dict() -> None:
    headers = {"Content-Type": "application/json", "Accept": "text/html"}
    result = extract_headers(headers)
    assert result == {"content-type": ["application/json"], "accept": ["text/html"]}


def testbuild_urllib3_response_json_body() -> None:
    response = build_urllib3_response(
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
        "https://example.com",
    )
    assert response.status == 200
    data = response.data
    assert b'"key"' in data
    assert b'"value"' in data


def testbuild_urllib3_response_content_length_recomputed() -> None:
    """content-length must match the re-serialized JSON body, not the original stored value."""
    original_body = {"key": "value"}
    wrong_length = "999"
    response = build_urllib3_response(
        HttpResponse(
            200,
            {"content-type": ["application/json"], "content-length": [wrong_length]},
            Body("json", original_body),
        ),
        "https://example.com",
    )
    import json

    expected = json.dumps(original_body).encode()
    assert response.headers["content-length"] == str(len(expected))
    assert response.data == expected


def testbuild_urllib3_response_content_length_absent_stays_absent() -> None:
    response = build_urllib3_response(
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"a": 1})),
        "https://example.com",
    )
    assert "content-length" not in response.headers


def testbuild_urllib3_response_text_body() -> None:
    response = build_urllib3_response(
        HttpResponse(200, body=Body("text", "hello world")),
        "https://example.com",
    )
    assert response.data == b"hello world"


def testbuild_urllib3_response_binary_body() -> None:
    response = build_urllib3_response(
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
        "https://example.com",
    )
    assert response.data == b"\x00\x01\x02"


def testbuild_urllib3_response_none_body() -> None:
    response = build_urllib3_response(
        HttpResponse(200, body=Body("none")),
        "https://example.com",
    )
    assert response.data == b""


def testbuild_urllib3_response_headers() -> None:
    response = build_urllib3_response(
        HttpResponse(200, {"x-custom": ["a", "b"]}, Body("none")),
        "https://example.com",
    )
    assert response.headers.getlist("x-custom") == ["a", "b"]


def test_record_urllib3_rewrites_content_length(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recorded response carrying content-length has it rewritten to the stored body length."""
    path = os.path.join(str(tmp_path), "clen.yaml")
    body = b'{"recorded": true}'
    fake_response = urllib3.response.HTTPResponse(
        body=io.BytesIO(body),
        headers={"content-type": "application/json", "content-length": "999"},
        status=200,
        preload_content=False,
    )
    fake_response._body = body
    monkeypatch.setattr(
        urllib3.connectionpool.HTTPConnectionPool,
        "urlopen",
        lambda self, method, url, **kwargs: fake_response,
    )
    with use_cassette(path, record_mode="all", intercept=["urllib3"]):
        resp = urllib3.PoolManager().request("GET", "https://example.com/clen")
    assert resp.headers["content-length"] == str(len(body))
    monkeypatch.undo()
