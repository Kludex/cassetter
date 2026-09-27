from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from cassetter import use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def greet(ws: ServerConnection) -> None:
    await ws.recv()
    await ws.send("hello")
    await ws.send(b"\x00\x01")
    await ws.close(4000, "bye")


@pytest.fixture
async def uri() -> AsyncIterator[str]:
    async with serve(greet, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}/"


async def converse(uri: str) -> tuple[list[str | bytes], int | None, str | None]:
    async with websockets.connect(uri) as ws:
        await ws.send("hi")
        received: list[str | bytes] = [await ws.recv(decode=False), await ws.recv(decode=True)]
        with pytest.raises(ConnectionClosedError):
            await ws.recv()
        return received, ws.close_code, ws.close_reason


@pytest.mark.anyio
async def test_recv_decode_and_close_state_match_a_live_connection(tmp_path: Path, uri: str) -> None:
    path = tmp_path / "ws.yaml"
    expected = ([b"hello", "\x00\x01"], 4000, "bye")

    with use_cassette(path, record_mode="once", intercept=["websockets"]):
        assert await converse(uri) == expected

    with use_cassette(path, record_mode="none", intercept=["websockets"]):
        assert await converse(uri) == expected


@pytest.mark.anyio
async def test_replay_iteration_ends_with_the_recorded_close(tmp_path: Path, uri: str) -> None:
    path = tmp_path / "ws.yaml"
    with use_cassette(path, record_mode="once", intercept=["websockets"]):
        await converse(uri)

    with use_cassette(path, record_mode="none", intercept=["websockets"]):
        async with websockets.connect(uri) as ws:
            assert (ws.close_code, ws.close_reason) == (None, None)
            with pytest.raises(ConnectionClosedError):
                [message async for message in ws]
            assert (ws.close_code, ws.close_reason) == (4000, "bye")


@pytest.mark.anyio
async def test_replay_close_ends_the_connection(tmp_path: Path, uri: str) -> None:
    path = tmp_path / "ws.yaml"
    with use_cassette(path, record_mode="once", intercept=["websockets"]):
        await converse(uri)

    with use_cassette(path, record_mode="none", intercept=["websockets"]):
        async with websockets.connect(uri) as ws:
            await ws.close(1001, "leaving")
            assert (ws.close_code, ws.close_reason) == (1001, "leaving")
            with pytest.raises(ConnectionClosedOK):
                await ws.recv()
            await ws.close()
            assert ws.close_code == 1001
