from __future__ import annotations

import os

import httpx
import pytest

from vcr_but_better._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from vcr_but_better.cassette import Cassette, NoMatchError
from vcr_but_better.context import use_cassette
from vcr_but_better.intercept._httpx import HttpxInterceptor, _build_httpx_response, _extract_headers_skip_encoding
from vcr_but_better.recording import RecordMode

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: object) -> str:
    return os.path.join(str(tmp_path), "httpx_test.yaml")


@pytest.fixture
def preloaded_cassette(cassette_path: str) -> str:
    """Create a cassette file with a pre-recorded interaction."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest(
                "GET",
                "https://httpbin.org/get",
                {"host": ["httpbin.org"]},
            ),
            response=HttpResponse(
                200,
                {"content-type": ["application/json"]},
                Body("json", {"origin": "127.0.0.1", "url": "https://httpbin.org/get"}),
            ),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(cassette_path)
    return cassette_path


@pytest.mark.anyio
async def test_replay_from_cassette(preloaded_cassette: str) -> None:
    async with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")

    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "127.0.0.1"


@pytest.mark.anyio
async def test_no_match_raises(preloaded_cassette: str) -> None:
    async with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            with pytest.raises(NoMatchError):
                await client.get("https://httpbin.org/post")


@pytest.mark.anyio
async def test_record_and_replay(cassette_path: str) -> None:
    """Test that we can record an interaction and then replay it."""
    # Create cassette with recording
    cassette = Cassette(cassette_path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record(
        method="GET",
        uri="https://example.com/api/data",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={"content-type": ["application/json"]},
        response_body=b'{"items": [1, 2, 3]}',
    )
    cassette.save()

    # Replay
    async with use_cassette(cassette_path, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api/data")

    assert response.status_code == 200
    assert response.json() == {"items": [1, 2, 3]}


def test_sync_replay(preloaded_cassette: str) -> None:
    cassette = Cassette(preloaded_cassette, record_mode=RecordMode.NONE)
    cassette.load()

    interceptor = HttpxInterceptor()
    interceptor.install(cassette)

    try:
        with httpx.Client() as client:
            response = client.get("https://httpbin.org/get")
        assert response.status_code == 200
        assert response.json()["origin"] == "127.0.0.1"
    finally:
        interceptor.uninstall()


def test_sync_no_match_raises(preloaded_cassette: str) -> None:
    cassette = Cassette(preloaded_cassette, record_mode=RecordMode.NONE)
    cassette.load()

    interceptor = HttpxInterceptor()
    interceptor.install(cassette)

    try:
        with httpx.Client() as client:
            with pytest.raises(NoMatchError):
                client.get("https://httpbin.org/unknown")
    finally:
        interceptor.uninstall()


def test_sync_record(cassette_path: str) -> None:
    cassette = Cassette(cassette_path, record_mode=RecordMode.ALL)
    cassette.load()

    interceptor = HttpxInterceptor()
    interceptor.install(cassette)

    try:
        transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"created": True}))
        with httpx.Client(transport=transport) as client:
            response = client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1
    finally:
        interceptor.uninstall()


@pytest.mark.anyio
async def test_async_record(cassette_path: str) -> None:
    cassette = Cassette(cassette_path, record_mode=RecordMode.ALL)
    cassette.load()

    interceptor = HttpxInterceptor()
    interceptor.install(cassette)

    try:
        transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"created": True}))
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1
    finally:
        interceptor.uninstall()


class TestBuildHttpxResponse:
    def test_json_body(self) -> None:
        response = _build_httpx_response(
            HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
        )
        assert response.json() == {"key": "value"}

    def test_text_body(self) -> None:
        response = _build_httpx_response(
            HttpResponse(200, body=Body("text", "hello world")),
        )
        assert response.text == "hello world"

    def test_binary_body(self) -> None:
        response = _build_httpx_response(
            HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
        )
        assert response.content == b"\x00\x01\x02"

    def test_none_body(self) -> None:
        response = _build_httpx_response(
            HttpResponse(200, body=Body("none")),
        )
        assert response.content == b""


def test_install_uninstall() -> None:
    interceptor = HttpxInterceptor()
    original_async_init = httpx.AsyncClient.__init__
    original_sync_init = httpx.Client.__init__

    cassette = Cassette("/nonexistent", record_mode=RecordMode.NONE)
    cassette.load()

    interceptor.install(cassette)
    assert httpx.AsyncClient.__init__ is not original_async_init
    assert httpx.Client.__init__ is not original_sync_init

    interceptor.uninstall()
    assert httpx.AsyncClient.__init__ is original_async_init
    assert httpx.Client.__init__ is original_sync_init


def test_extract_headers_skip_encoding() -> None:
    headers = httpx.Headers({"content-type": "text/html", "content-encoding": "gzip", "x-custom": "val"})
    result = _extract_headers_skip_encoding(headers)
    assert "content-encoding" not in result
    assert result["content-type"] == ["text/html"]
    assert result["x-custom"] == ["val"]
