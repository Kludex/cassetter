from __future__ import annotations

import os

import pytest
import requests
import requests.adapters

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.intercept._requests import (
    RequestsInterceptor,
    VCRAdapter,
    _build_requests_response,
    _extract_headers,
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


def test_vcr_adapter_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    real_adapter = requests.adapters.HTTPAdapter()
    adapter = VCRAdapter(cassette, real_adapter)

    req = requests.Request("GET", "https://example.com/api").prepare()
    response = adapter.send(req)

    assert response.status_code == 200
    assert response.json() == {"data": "hello"}


def test_vcr_adapter_record(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    fake_response = requests.Response()
    fake_response.status_code = 201
    fake_response._content = b'{"created": true}'  # type: ignore[attr-defined]
    fake_response.headers["content-type"] = "application/json"

    class MockAdapter(requests.adapters.HTTPAdapter):
        def send(self, request: requests.PreparedRequest, **kwargs: object) -> requests.Response:  # type: ignore[override]
            return fake_response

    adapter = VCRAdapter(cassette, MockAdapter())
    req = requests.Request("POST", "https://example.com/create").prepare()
    response = adapter.send(req)

    assert response.status_code == 201
    assert len(cassette.interactions) == 1


def test_requests_interceptor_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = RequestsInterceptor()
    interceptor.install(cassette)

    try:
        response = requests.get("https://example.com/api")
        assert response.status_code == 200
        assert response.json() == {"data": "hello"}
    finally:
        interceptor.uninstall()


def test_requests_interceptor_record(tmp_path: object, monkeypatch: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    fake_response = requests.Response()
    fake_response.status_code = 200
    fake_response._content = b'{"recorded": true}'  # type: ignore[attr-defined]
    fake_response.headers["content-type"] = "application/json"

    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(
        requests.adapters.HTTPAdapter,
        "send",
        lambda self, request, **kwargs: fake_response,
    )

    interceptor = RequestsInterceptor()
    interceptor.install(cassette)

    try:
        response = requests.get("https://example.com/new-endpoint")
        assert response.status_code == 200
        assert len(cassette.interactions) == 1
    finally:
        interceptor.uninstall()
        mp.undo()


def test_requests_interceptor_install_uninstall() -> None:
    interceptor = RequestsInterceptor()
    original_send = requests.Session.send
    cassette = Cassette("/nonexistent", record_mode=RecordMode.NONE)
    cassette.load()

    interceptor.install(cassette)
    assert requests.Session.send is not original_send

    interceptor.uninstall()
    assert requests.Session.send is original_send


def test_extract_headers_none() -> None:
    assert _extract_headers(None) == {}


def test_extract_headers_dict() -> None:
    headers = {"Content-Type": "application/json", "Accept": "text/html"}
    result = _extract_headers(headers)
    assert result == {"content-type": ["application/json"], "accept": ["text/html"]}


def test_vcr_adapter_no_match(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    real_adapter = requests.adapters.HTTPAdapter()
    adapter = VCRAdapter(cassette, real_adapter)

    req = requests.Request("DELETE", "https://example.com/unknown").prepare()
    with pytest.raises(NoMatchError):
        adapter.send(req)


def test_requests_interceptor_no_match(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = RequestsInterceptor()
    interceptor.install(cassette)

    try:
        with pytest.raises(NoMatchError):
            requests.delete("https://example.com/unknown")
    finally:
        interceptor.uninstall()


def test_build_requests_response_json_body() -> None:
    response = _build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert response.json() == {"key": "value"}


def test_build_requests_response_text_body() -> None:
    response = _build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert response.text == "hello world"


def test_build_requests_response_binary_body() -> None:
    response = _build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert response.content == b"\x00\x01\x02"


def test_build_requests_response_none_body() -> None:
    response = _build_requests_response(
        requests.Request("GET", "https://example.com").prepare(),
        HttpResponse(200, body=Body("none")),
    )
    assert response.content == b""
