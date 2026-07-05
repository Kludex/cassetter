from __future__ import annotations

import os

import pytest
import requests
import requests.adapters

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._requests import (
    RequestsInterceptor,
    build_requests_response,
    extract_headers,
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


def test_requests_interceptor_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["requests"]):
        response = requests.get("https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}


def test_requests_interceptor_record(tmp_path: object, monkeypatch: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")

    fake_response = requests.Response()
    fake_response.status_code = 200
    fake_response._content = b'{"recorded": true}'  # type: ignore[attr-defined]
    fake_response.headers["content-type"] = "application/json"

    mp = pytest.MonkeyPatch()
    mp.setattr(
        requests.adapters.HTTPAdapter,
        "send",
        lambda self, request, **kwargs: fake_response,
    )

    with use_cassette(path, record_mode="all", intercept=["requests"]) as cassette:
        response = requests.get("https://example.com/new-endpoint")
        assert response.status_code == 200
        assert len(cassette.interactions) == 1

    mp.undo()


def test_requests_interceptor_install_uninstall() -> None:
    interceptor = RequestsInterceptor()
    original_send = requests.Session.send

    interceptor.install()
    assert requests.Session.send is not original_send

    interceptor.uninstall()
    assert requests.Session.send is original_send


def testextract_headers_none() -> None:
    assert extract_headers(None) == {}


def testextract_headers_dict() -> None:
    headers = {"Content-Type": "application/json", "Accept": "text/html"}
    result = extract_headers(headers)
    assert result == {"content-type": ["application/json"], "accept": ["text/html"]}


def test_requests_interceptor_no_match(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _preload_cassette(path)

    with use_cassette(path, record_mode="none", intercept=["requests"]):
        with pytest.raises(NoMatchError):
            requests.delete("https://example.com/unknown")


def testbuild_requests_response_json_body() -> None:
    response = build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert response.json() == {"key": "value"}


def testbuild_requests_response_text_body() -> None:
    response = build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert response.text == "hello world"


def testbuild_requests_response_binary_body() -> None:
    response = build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert response.content == b"\x00\x01\x02"


def testbuild_requests_response_none_body() -> None:
    response = build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("none")),
    )
    assert response.content == b""


def test_recorded_response_headers_drop_content_encoding() -> None:
    from cassetter.intercept._requests import extract_headers_skip_encoding

    result = extract_headers_skip_encoding({"Content-Encoding": "gzip", "Content-Type": "text/html"})
    assert "content-encoding" not in result
    assert result["content-type"] == ["text/html"]
