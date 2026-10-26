from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close

from cassetter import Body, ResponseMismatchError, WsFrame, use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


CONVERSATION = ([b"hello", "\x00\x01"], 4000, "bye")


async def converse(uri: str) -> tuple[list[str | bytes], int | None, str | None]:
    async with websockets.connect(uri) as ws:
        await ws.send("hi")
        received: list[str | bytes] = [await ws.recv(decode=False), await ws.recv(decode=True)]
        with pytest.raises(ConnectionClosedError):
            await ws.recv()
        return received, ws.close_code, ws.close_reason


async def record(path: Path, uri: str) -> tuple[list[str | bytes], int | None, str | None]:
    with use_cassette(path, record_mode="once", intercept=["websockets"]):
        return await converse(uri)


@pytest.fixture
async def recorded(tmp_path: Path, ws_uri: str) -> Path:
    path = tmp_path / "ws.yaml"
    # Its own task: on Python 3.11, catching a live connection's close stops coverage tracing the awaiting frame.
    assert await asyncio.create_task(record(path, ws_uri)) == CONVERSATION
    return path


@pytest.mark.anyio
async def test_replay_matches_the_live_connection(recorded: Path, ws_uri: str) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"]):
        assert await converse(ws_uri) == CONVERSATION


@pytest.mark.anyio
async def test_replay_iteration_ends_with_the_recorded_close(recorded: Path, ws_uri: str) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"]):
        async with websockets.connect(ws_uri) as ws:
            assert (ws.close_code, ws.close_reason) == (None, None)
            with pytest.raises(ConnectionClosedError):
                [message async for message in ws]
            assert (ws.close_code, ws.close_reason) == (4000, "bye")
            with pytest.raises(ConnectionClosedError):
                await ws.send("late")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "closed"), [(1001, ConnectionClosedOK), (4000, ConnectionClosedError)], ids=["going-away", "error"]
)
async def test_replay_close_ends_the_connection(
    recorded: Path, ws_uri: str, code: int, closed: type[Exception]
) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"]):
        async with websockets.connect(ws_uri) as ws:
            await ws.close(code, "leaving")
            assert (ws.close_code, ws.close_reason) == (code, "leaving")
            with pytest.raises(closed):
                await ws.recv()
            with pytest.raises(closed):
                await ws.send("late")
            await ws.close()
            assert ws.close_code == code


@pytest.mark.anyio
async def test_frames_running_out_close_the_connection_normally(tmp_path: Path) -> None:
    path = tmp_path / "ws.yaml"
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record_ws("wss://ws.example.com/", {}, [WsFrame("recv", "text", Body("text", "hi"))])

    with use_cassette(path, record_mode="none", intercept=["websockets"]):
        async with websockets.connect("wss://ws.example.com/") as ws:
            assert await ws.recv() == "hi"
            with pytest.raises(ConnectionClosedOK) as closed:
                await ws.recv()
            assert closed.value.rcvd == Close(1000, "")
            assert (ws.close_code, ws.close_reason) == (1000, "")


async def verify(path: Path, uri: str) -> tuple[list[str | bytes], int | None, str | None]:
    with use_cassette(path, record_mode="verify", intercept=["websockets"]):
        return await converse(uri)


@pytest.mark.anyio
async def test_verify_connects_live(recorded: Path, ws_uri: str) -> None:
    before = recorded.read_text()
    assert await asyncio.create_task(verify(recorded, ws_uri)) == CONVERSATION
    assert recorded.read_text() == before


@pytest.mark.anyio
async def test_verify_reports_different_received_frames(tmp_path: Path, ws_uri: str) -> None:
    path = tmp_path / "ws.yaml"
    frames = [
        WsFrame("send", "text", Body("text", "hi")),
        WsFrame("recv", "text", Body("text", '{"greeting": "hello"}')),
        WsFrame("recv", "binary", Body("binary", b"\x00\x01")),
        WsFrame("recv", "close", Body("binary", b"\x0f\xa0bye")),
    ]
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record_ws(ws_uri, {}, frames)

    with pytest.raises(ResponseMismatchError) as mismatch:
        await asyncio.create_task(verify(path, ws_uri))
    assert str(mismatch.value) == (
        f"cassette {path}, WebSocket {ws_uri}\n--- recorded\n+++ live\n@@ -1,6 +1,3 @@\n"
        '-@@ text 1 @@\n-{\n-  "greeting": "hello"\n-}\n+text 1: hello\n'
        " binary 2: b'\\x00\\x01'\n close 3: 4000 bye"
    )
