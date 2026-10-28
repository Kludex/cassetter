from __future__ import annotations

import json
import os
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("pyreqwest")

from pyreqwest.client import ClientBuilder, SyncClientBuilder
from pyreqwest.request import RequestBuilder
from pyreqwest.simple.request import pyreqwest_get as async_get
from pyreqwest.simple.sync_request import pyreqwest_get, pyreqwest_post

from cassetter import NoMatchError, RawRequest, ResponseMismatchError, SkipRecording, use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def received() -> list[tuple[str, bytes]]:
    return []


@pytest.fixture
def url(received: list[tuple[str, bytes]]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.reply()

        def do_POST(self) -> None:
            self.reply()

        def reply(self) -> None:
            length = int(self.headers.get("content-length", 0))
            received.append((self.command, self.rfile.read(length)))
            body = json.dumps({"path": self.path, "calls": len(received)}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("x-tag", "a")
            self.send_header("x-tag", "b")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def path(tmp_path: Path) -> str:
    return os.path.join(tmp_path, "pyreqwest.yaml")


def test_sync_client_records_and_replays(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]) as cassette:
        with SyncClientBuilder().build() as client:
            recorded = client.post(f"{url}/items").body_json({"name": "x"}).build().send()
    assert recorded.json() == {"path": "/items", "calls": 1}
    assert cassette.interactions[0].request.body.content == {"name": "x"}

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        with SyncClientBuilder().build() as client:
            replayed = client.post(f"{url}/items").body_json({"name": "x"}).build().send()
    assert replayed.status == 200
    assert replayed.json() == {"path": "/items", "calls": 1}
    assert replayed.get_header_all("x-tag") == ["a", "b"]
    assert len(received) == 1


@pytest.mark.anyio
async def test_async_client_records_and_replays(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
        async with ClientBuilder().build() as client:
            recorded = await client.get(f"{url}/items").build().send()
            assert await recorded.json() == {"path": "/items", "calls": 1}

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        async with ClientBuilder().build() as client:
            replayed = await client.get(f"{url}/items").build().send()
            assert await replayed.json() == {"path": "/items", "calls": 1}
    assert len(received) == 1


def test_streamed_request_and_response(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]) as cassette:
        with SyncClientBuilder().build() as client:
            request = client.post(f"{url}/upload").body_stream(iter([b"ab", b"cd"])).build_streamed()
            with request as response:
                assert json.loads(response.body_reader.bytes().to_bytes()) == {"path": "/upload", "calls": 1}
    assert received == [("POST", b"abcd")]
    assert cassette.interactions[0].request.body.content == "abcd"

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        with SyncClientBuilder().build() as client:
            request = client.post(f"{url}/upload").body_stream(iter([b"ab", b"cd"])).build_streamed()
            with request as response:
                assert json.loads(response.body_reader.bytes().to_bytes()) == {"path": "/upload", "calls": 1}
    assert len(received) == 1


@pytest.mark.anyio
async def test_async_streamed_request_body(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"ab"
        yield b"cd"

    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
        async with ClientBuilder().build() as client:
            await client.post(f"{url}/upload").body_stream(chunks()).build().send()
    assert received == [("POST", b"abcd")]


def test_simple_requests_record_and_replay(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
        pyreqwest_get(f"{url}/simple").send()
        pyreqwest_post(f"{url}/simple").body_text("hi").send()

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]) as cassette:
        assert pyreqwest_get(f"{url}/simple").send().json() == {"path": "/simple", "calls": 1}
        assert pyreqwest_post(f"{url}/simple").body_text("hi").send().json() == {"path": "/simple", "calls": 2}
    assert cassette.all_played
    assert len(received) == 2


@pytest.mark.anyio
async def test_async_simple_request_replays(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
        await async_get(f"{url}/simple").send()

    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        response = await async_get(f"{url}/simple").send()
        assert await response.json() == {"path": "/simple", "calls": 1}
    assert len(received) == 1


def test_no_match_raises(path: str) -> None:
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        with pytest.raises(NoMatchError):
            pyreqwest_get("https://example.com/missing").send()


def test_verify_compares_live_response(url: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
        pyreqwest_get(f"{url}/verify").send()

    with use_cassette(path, record_mode="verify", intercept=["pyreqwest"]):
        with pytest.raises(ResponseMismatchError, match='"calls": 2'):
            pyreqwest_get(f"{url}/verify").send()


@pytest.mark.anyio
async def test_bypass_goes_live(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"], ignore_localhost=True):
        assert pyreqwest_get(f"{url}/live").send().status == 200
        assert (await async_get(f"{url}/live").send()).status == 200
    assert len(received) == 2


@pytest.mark.anyio
async def test_skip_recording_goes_live(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    def hook(request: RawRequest) -> RawRequest:
        raise SkipRecording

    with use_cassette(path, record_mode="all", intercept=["pyreqwest"], before_record_request=hook) as cassette:
        assert pyreqwest_get(f"{url}/live").send().status == 200
        assert (await async_get(f"{url}/live").send()).status == 200
    assert cassette.interactions == []
    assert len(received) == 2


def test_request_sent_after_cassette_exits_goes_live(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with SyncClientBuilder().build() as client:
        with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
            request = client.get(f"{url}/later").build()
        assert request.send().status == 200
    assert len(received) == 1


def test_request_built_before_cassette_is_refused(url: str, path: str, received: list[tuple[str, bytes]]) -> None:
    with SyncClientBuilder().build() as client:
        request = client.get(f"{url}/early").build()
        with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
            with pytest.raises(RuntimeError, match="built before the cassette was entered"):
                request.send()
    assert received == []


@pytest.mark.anyio
async def test_streamed_request_built_before_cassette_is_refused(url: str, path: str) -> None:
    async with ClientBuilder().build() as client:
        request = client.get(f"{url}/early").build_streamed()
        with use_cassette(path, record_mode="all", intercept=["pyreqwest"]):
            with pytest.raises(RuntimeError, match="built before the cassette was entered"):
                await request.__aenter__()


def test_bypassed_request_built_before_cassette_goes_live(
    url: str, path: str, received: list[tuple[str, bytes]]
) -> None:
    with SyncClientBuilder().build() as client:
        request = client.get(f"{url}/early").build()
        with use_cassette(path, record_mode="none", intercept=["pyreqwest"], ignore_localhost=True):
            assert request.send().status == 200
    assert len(received) == 1


def test_uninstall_restores_builders(path: str) -> None:
    original = RequestBuilder.build
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        assert RequestBuilder.build is not original
    assert RequestBuilder.build is original
