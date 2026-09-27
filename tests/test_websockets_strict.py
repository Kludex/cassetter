from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
import websockets
from websockets.exceptions import ConnectionClosedOK

from cassetter import Body, NoMatchError, WsFrame, use_cassette

if TYPE_CHECKING:
    from cassetter._core import Matcher

URI = "wss://ws.example.com/"
STRICT: list[Matcher] = ["method", "uri", "body"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def text(direction: Literal["send", "recv"], content: str) -> WsFrame:
    return WsFrame(direction, "text", Body("text", content))


@pytest.fixture
def recorded(tmp_path: Path) -> Path:
    path = tmp_path / "ws.yaml"
    frames = [
        text("send", "hi"),
        text("recv", "hello"),
        text("send", "bye"),
        text("recv", "ciao"),
        WsFrame("recv", "close", Body("binary", struct.pack(">H", 1000))),
    ]
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record_ws(URI, {}, frames)
    return path


@pytest.mark.anyio
async def test_recv_waits_for_the_sends_recorded_before_it(recorded: Path) -> None:
    events: list[str] = []

    async def read(ws: websockets.ClientConnection) -> None:
        async for message in ws:
            events.append(f"recv {message!r}")

    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        async with websockets.connect(URI) as ws:
            reader = asyncio.create_task(read(ws))
            await asyncio.sleep(0)
            assert events == []
            for message in ("hi", "bye"):
                events.append(f"send {message}")
                await ws.send(message)
                await asyncio.sleep(0)
            await reader

    assert events == ["send hi", "recv 'hello'", "send bye", "recv 'ciao'"]


@pytest.mark.anyio
async def test_a_changed_send_fails(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        async with websockets.connect(URI) as ws:
            with pytest.raises(NoMatchError, match="send #1 to wss://ws.example.com/ does not match"):
                await ws.send("howdy")
            await ws.send("hi")
            await ws.send("bye")


@pytest.mark.anyio
async def test_an_extra_send_fails(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        async with websockets.connect(URI) as ws:
            await ws.send("hi")
            await ws.send("bye")
            with pytest.raises(NoMatchError, match="send #3 .* is not in the recording, which has 2"):
                await ws.send("again")


@pytest.mark.anyio
async def test_closing_with_a_send_missing_fails(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        with pytest.raises(NoMatchError, match="closed with 1 recorded send"):
            async with websockets.connect(URI) as ws:
                await ws.send("hi")
                assert await ws.recv() == "hello"


@pytest.mark.anyio
async def test_a_missing_send_does_not_hide_the_error_that_ended_the_connection(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        with pytest.raises(RuntimeError, match="boom"):
            async with websockets.connect(URI):
                raise RuntimeError("boom")

    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        iterator = cast("AsyncGenerator[Any, None]", aiter(websockets.connect(URI)))
        await anext(iterator)
        await iterator.aclose()


@pytest.mark.anyio
async def test_closing_wakes_a_waiting_reader(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        ws = await websockets.connect(URI)
        reader = asyncio.create_task(ws.recv())
        await asyncio.sleep(0)
        with pytest.raises(NoMatchError):
            await ws.close()
        with pytest.raises(ConnectionClosedOK):
            await reader


@pytest.mark.anyio
async def test_reconnecting_does_not_rewind_the_recording(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["websockets"], match_on=STRICT):
        async with websockets.connect(URI) as ws:
            await ws.send("hi")
            await ws.send("bye")
        with pytest.raises(NoMatchError, match="already replayed"):
            await websockets.connect(URI)


@pytest.mark.anyio
async def test_sends_compare_after_write_time_filtering(tmp_path: Path) -> None:
    path = tmp_path / "ws.yaml"
    login = '{"token": "s3cret", "user": "me"}'
    with use_cassette(path, record_mode="all", intercept=[], body_scrub_patterns=["token"]) as cassette:
        cassette.record_ws(URI, {}, [text("send", login)])

    with use_cassette(
        path, record_mode="none", intercept=["websockets"], match_on=STRICT, body_scrub_patterns=["token"]
    ):
        async with websockets.connect(URI) as ws:
            await ws.send(login)
