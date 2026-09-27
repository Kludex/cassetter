from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import websockets
from websockets.asyncio.server import ServerConnection, serve

from cassetter import Body, SkipRecording, WsFrame, use_cassette
from cassetter.websockets import VCRWebSocketReplay

if TYPE_CHECKING:
    from cassetter._core import Matcher

STRICT: list[Matcher] = ["method", "uri", "body"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def echo(ws: ServerConnection) -> None:
    async for message in ws:
        await ws.send(message)


@pytest.fixture
async def echo_uri() -> AsyncIterator[str]:
    async with serve(echo, "localhost", 0) as server:
        yield f"ws://localhost:{server.sockets[0].getsockname()[1]}/"


def normalize_sends(frame: WsFrame) -> WsFrame:
    content = frame.body.content
    if frame.direction != "send" or not isinstance(content, str):
        return frame
    if content == "ping":
        raise SkipRecording
    return WsFrame("send", "text", Body("text", re.sub(r"id-\d+", "id-<n>", content)), frame.offset_ms)


@pytest.mark.anyio
async def test_the_hook_normalizes_recorded_and_replayed_sends(tmp_path: Path, echo_uri: str) -> None:
    path = tmp_path / "ws.yaml"

    with use_cassette(path, record_mode="once", intercept=["websockets"], before_record_ws_frame=normalize_sends):
        async with websockets.connect(echo_uri) as ws:
            await ws.send("ping")
            assert await ws.recv() == "ping"
            await ws.send("hello id-123")
            assert await ws.recv() == "hello id-123"

    with use_cassette(path, record_mode="none", intercept=[]) as cassette:
        frames = cassette.ws_interactions[0].frames
    assert [(frame.direction, frame.body.content) for frame in frames] == [
        ("recv", "ping"),
        ("send", "hello id-<n>"),
        ("recv", "hello id-123"),
    ]

    with use_cassette(
        path, record_mode="none", intercept=["websockets"], match_on=STRICT, before_record_ws_frame=normalize_sends
    ):
        async with websockets.connect(echo_uri) as ws:
            await ws.send("ping")
            assert await ws.recv() == "ping"
            await ws.send("hello id-456")
            assert await ws.recv() == "hello id-123"
            await ws.send("ping")


@pytest.mark.anyio
async def test_received_frames_report_replay_progress(tmp_path: Path) -> None:
    path = tmp_path / "ws.yaml"
    frames = [WsFrame("recv", "text", Body("text", word), offset_ms) for word, offset_ms in (("a", 0), ("b", 1500))]
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record_ws("wss://ws.example.com/", {}, frames)

    with use_cassette(path, record_mode="none", intercept=["websockets"]):
        async with websockets.connect("wss://ws.example.com/") as ws:
            assert isinstance(ws, VCRWebSocketReplay)
            assert ws.received_frames == []
            assert await ws.recv() == "a"
            ws.received_frames.clear()
            assert await ws.recv() == "b"
            assert [frame.offset_ms for frame in ws.received_frames] == [0, 1500]
