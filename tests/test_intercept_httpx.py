from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from cassetter import RawRequest
from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._httpx import HttpxInterceptor, build_httpx_response, extract_headers_skip_encoding
from cassetter.recording import RecordMode

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
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")

    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "127.0.0.1"


@pytest.mark.anyio
async def test_no_match_raises(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
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
    with use_cassette(cassette_path, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api/data")

    assert response.status_code == 200
    assert response.json() == {"items": [1, 2, 3]}


def test_sync_replay(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        with httpx.Client() as client:
            response = client.get("https://httpbin.org/get")
        assert response.status_code == 200
        assert response.json()["origin"] == "127.0.0.1"


def test_sync_no_match_raises(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        with httpx.Client() as client:
            with pytest.raises(NoMatchError):
                client.get("https://httpbin.org/unknown")


def test_sync_record(cassette_path: str) -> None:
    with use_cassette(cassette_path, record_mode="all", intercept=["httpx"]) as cassette:
        transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"created": True}))
        with httpx.Client(transport=transport) as client:
            response = client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1


@pytest.mark.anyio
async def test_async_record(cassette_path: str) -> None:
    with use_cassette(cassette_path, record_mode="all", intercept=["httpx"]) as cassette:
        transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"created": True}))
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1


def test_build_httpx_response_json_body() -> None:
    response = build_httpx_response(
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert response.json() == {"key": "value"}


def test_build_httpx_response_text_body() -> None:
    response = build_httpx_response(
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert response.text == "hello world"


def test_build_httpx_response_binary_body() -> None:
    response = build_httpx_response(
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert response.content == b"\x00\x01\x02"


def test_build_httpx_response_none_body() -> None:
    response = build_httpx_response(
        HttpResponse(200, body=Body("none")),
    )
    assert response.content == b""


def test_install_uninstall() -> None:
    interceptor = HttpxInterceptor()
    original_async_init = httpx.AsyncClient.__init__
    original_sync_init = httpx.Client.__init__

    interceptor.install()
    assert httpx.AsyncClient.__init__ is not original_async_init
    assert httpx.Client.__init__ is not original_sync_init

    interceptor.uninstall()
    assert httpx.AsyncClient.__init__ is original_async_init
    assert httpx.Client.__init__ is original_sync_init


@pytest.mark.anyio
async def test_replay_streaming_request_body(preloaded_cassette: str) -> None:
    """Streaming request bodies (e.g. file uploads) raise RequestNotRead on .content access."""

    async def body_stream() -> AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.request("GET", "https://httpbin.org/get", content=body_stream())

    assert response.status_code == 200
    assert response.json()["origin"] == "127.0.0.1"


def test_extract_headers_skip_encoding() -> None:
    headers = httpx.Headers({"content-type": "text/html", "content-encoding": "gzip", "x-custom": "val"})
    result = extract_headers_skip_encoding(headers)
    assert "content-encoding" not in result
    assert result["content-type"] == ["text/html"]
    assert result["x-custom"] == ["val"]


def test_sync_replay_streaming_request_body(preloaded_cassette: str) -> None:
    """Sync streaming request bodies raise RequestNotRead on .content access."""

    def body_stream() -> Iterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        with httpx.Client() as client:
            response = client.request("GET", "https://httpbin.org/get", content=body_stream())

    assert response.status_code == 200
    assert response.json()["origin"] == "127.0.0.1"


def test_sync_hook_rewrites_to_match(preloaded_cassette: str) -> None:
    """A sync before_record_request hook that rewrites the URI to match replays without network."""

    def hook(request: RawRequest) -> RawRequest:
        request.uri = "https://httpbin.org/get"
        return request

    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"], before_record_request=hook):
        with httpx.Client() as client:
            response = client.get("https://httpbin.org/original")
    assert response.status_code == 200
