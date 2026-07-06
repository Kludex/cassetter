from __future__ import annotations

import os

import httpx
import httpx2
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._httpx2 import Httpx2Interceptor, build_httpx2_response
from cassetter.recording import RecordMode

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: object) -> str:
    return os.path.join(str(tmp_path), "httpx2_test.yaml")


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
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx2"]):
        async with httpx2.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")

    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "127.0.0.1"


@pytest.mark.anyio
async def test_no_match_raises(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx2"]):
        async with httpx2.AsyncClient() as client:
            with pytest.raises(NoMatchError):
                await client.get("https://httpbin.org/post")


@pytest.mark.anyio
async def test_record_and_replay(cassette_path: str) -> None:
    """Test that we can record an interaction and then replay it."""
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

    with use_cassette(cassette_path, record_mode="none", intercept=["httpx2"]):
        async with httpx2.AsyncClient() as client:
            response = await client.get("https://example.com/api/data")

    assert response.status_code == 200
    assert response.json() == {"items": [1, 2, 3]}


def test_sync_replay(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx2"]):
        with httpx2.Client() as client:
            response = client.get("https://httpbin.org/get")
        assert response.status_code == 200
        assert response.json()["origin"] == "127.0.0.1"


def test_sync_no_match_raises(preloaded_cassette: str) -> None:
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx2"]):
        with httpx2.Client() as client:
            with pytest.raises(NoMatchError):
                client.get("https://httpbin.org/unknown")


def test_sync_record(cassette_path: str) -> None:
    with use_cassette(cassette_path, record_mode="all", intercept=["httpx2"]) as cassette:
        transport = httpx2.MockTransport(lambda request: httpx2.Response(201, json={"created": True}))
        with httpx2.Client(transport=transport) as client:
            response = client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1


@pytest.mark.anyio
async def test_async_record(cassette_path: str) -> None:
    with use_cassette(cassette_path, record_mode="all", intercept=["httpx2"]) as cassette:
        transport = httpx2.MockTransport(lambda request: httpx2.Response(201, json={"created": True}))
        async with httpx2.AsyncClient(transport=transport) as client:
            response = await client.get("https://example.com/create")
        assert response.status_code == 201
        assert len(cassette.interactions) == 1


def test_build_httpx2_response_json_body() -> None:
    response = build_httpx2_response(
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert response.json() == {"key": "value"}


def test_build_httpx2_response_text_body() -> None:
    response = build_httpx2_response(
        HttpResponse(200, body=Body("text", "hello world")),
    )
    assert response.text == "hello world"


def test_build_httpx2_response_binary_body() -> None:
    response = build_httpx2_response(
        HttpResponse(200, body=Body("binary", b"\x00\x01\x02")),
    )
    assert response.content == b"\x00\x01\x02"


def test_build_httpx2_response_none_body() -> None:
    response = build_httpx2_response(
        HttpResponse(200, body=Body("none")),
    )
    assert response.content == b""


def test_install_uninstall() -> None:
    interceptor = Httpx2Interceptor()
    original_async_init = httpx2.AsyncClient.__init__
    original_sync_init = httpx2.Client.__init__

    interceptor.install()
    assert httpx2.AsyncClient.__init__ is not original_async_init
    assert httpx2.Client.__init__ is not original_sync_init

    interceptor.uninstall()
    assert httpx2.AsyncClient.__init__ is original_async_init
    assert httpx2.Client.__init__ is original_sync_init


def test_httpx_and_httpx2_intercept_independently(cassette_path: str) -> None:
    """Both libraries can be intercepted under the same cassette without clashing."""

    with use_cassette(cassette_path, record_mode="all", intercept=["httpx", "httpx2"]) as cassette:
        transport1 = httpx.MockTransport(lambda request: httpx.Response(200, json={"lib": "httpx"}))
        with httpx.Client(transport=transport1) as client:
            assert client.get("https://example.com/one").status_code == 200

        transport2 = httpx2.MockTransport(lambda request: httpx2.Response(200, json={"lib": "httpx2"}))
        with httpx2.Client(transport=transport2) as client2:
            assert client2.get("https://example.com/two").status_code == 200

        assert len(cassette.interactions) == 2


@pytest.mark.anyio
async def test_replay_streaming_request_body(preloaded_cassette: str) -> None:
    """Streaming request bodies (e.g. file uploads) raise RequestNotRead on .content access."""

    async def body_stream():
        yield b"chunk1"
        yield b"chunk2"

    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx2"]):
        async with httpx2.AsyncClient() as client:
            response = await client.request("GET", "https://httpbin.org/get", content=body_stream())

    assert response.status_code == 200
    assert response.json()["origin"] == "127.0.0.1"
