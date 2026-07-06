from __future__ import annotations

import time
from collections.abc import AsyncIterator, Generator
from typing import Any

import websockets
import websockets.asyncio.client
from websockets.exceptions import ConnectionClosedOK

from cassetter._core import Body, WsFrame, WsInteraction
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError


class VCRWebSocket:
    """Wraps a real WebSocket connection to record sent/received frames."""

    def __init__(self, real_ws: Any, uri: str, headers: dict[str, list[str]]) -> None:
        self._real = real_ws
        self._uri = uri
        self._headers = headers
        self._frames: list[WsFrame] = []
        self._start_time = time.monotonic()

    async def send(self, message: str | bytes) -> None:
        offset_ms = int((time.monotonic() - self._start_time) * 1000)
        if isinstance(message, bytes):
            body = Body("binary", message)
            frame_type = "binary"
        else:
            body = Body("text", message)
            frame_type = "text"
        self._frames.append(WsFrame("send", frame_type, body, offset_ms))
        await self._real.send(message)

    async def recv(self) -> str | bytes:
        data: str | bytes = await self._real.recv()
        offset_ms = int((time.monotonic() - self._start_time) * 1000)
        if isinstance(data, bytes):
            body = Body("binary", data)
            frame_type = "binary"
        else:
            body = Body("text", data)
            frame_type = "text"
        self._frames.append(WsFrame("recv", frame_type, body, offset_ms))
        return data

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self._real.close(code, reason)
        self._flush()

    def _flush(self) -> None:
        cassette = get_current_cassette()
        if self._frames and cassette is not None:
            cassette.record_ws(self._uri, self._headers, self._frames)
            self._frames = []

    async def __aenter__(self) -> VCRWebSocket:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self._flush()
        await self._real.close()

    def __aiter__(self) -> VCRWebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.recv()
        except websockets.exceptions.ConnectionClosed:
            self._flush()
            raise StopAsyncIteration


class VCRWebSocketReplay:
    """Replays recorded WebSocket frames without a real connection."""

    def __init__(self, interaction: WsInteraction) -> None:
        self._frames = interaction.frames
        self._recv_frames = [f for f in self._frames if f.direction == "recv"]
        self._recv_index = 0

    async def send(self, message: str | bytes) -> None:
        pass

    async def recv(self) -> str | bytes:
        if self._recv_index >= len(self._recv_frames):
            # Recorded frames are exhausted; signal a clean end-of-stream the
            # way a real connection does, so `await ws.recv()` callers see
            # ConnectionClosed instead of a bare StopAsyncIteration.
            raise ConnectionClosedOK(None, None)
        frame = self._recv_frames[self._recv_index]
        self._recv_index += 1
        return frame_to_data(frame)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        pass

    async def __aenter__(self) -> VCRWebSocketReplay:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def __aiter__(self) -> VCRWebSocketReplay:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.recv()
        except ConnectionClosedOK:
            raise StopAsyncIteration


class _PatchedConnect:
    """Stand-in for ``websockets.connect`` supporting both call styles.

    ``async with websockets.connect(uri) as ws`` and
    ``ws = await websockets.connect(uri)`` both resolve to the same
    record/replay wrapper.
    """

    def __init__(self, original_connect: Any, uri: str, kwargs: dict[str, Any]) -> None:
        self._original_connect = original_connect
        self._uri = uri
        self._kwargs = kwargs
        self._ws: VCRWebSocket | VCRWebSocketReplay | None = None
        self._bypassed: Any = None

    async def _resolve(self) -> Any:
        cassette = get_current_cassette()
        if cassette is None or cassette.should_bypass(self._uri):
            self._bypassed = await self._original_connect(self._uri, **self._kwargs)  # pragma: no cover
            return self._bypassed  # pragma: no cover

        try:
            interaction = cassette.play_ws(self._uri)
            self._ws = VCRWebSocketReplay(interaction)
            return self._ws
        except NoMatchError:
            if not cassette.can_record:
                raise

        conn = self._original_connect(self._uri, **self._kwargs)  # pragma: no cover
        real_ws = await conn  # pragma: no cover
        headers = extract_ws_headers(self._kwargs)  # pragma: no cover
        self._ws = VCRWebSocket(real_ws, self._uri, headers)  # pragma: no cover
        return self._ws  # pragma: no cover

    async def _cleanup(self) -> None:
        # Flush recorded frames / close the connection regardless of call style.
        if self._ws is not None:
            await self._ws.__aexit__(None, None, None)
        elif self._bypassed is not None:  # pragma: no cover - bypass needs a live server
            await self._bypassed.close()

    def __await__(self) -> Generator[Any, None, Any]:
        return self._resolve().__await__()

    async def __aenter__(self) -> Any:
        return await self._resolve()

    async def __aexit__(self, *args: Any) -> None:
        await self._cleanup()

    def __aiter__(self) -> Any:
        # `async for ws in connect(...)` yields one connection then cleans up in
        # the generator's finally - Python does not call __aexit__ on async-for
        # iterations, so recorded frames would otherwise never be flushed.
        return self._reconnect()

    async def _reconnect(self) -> AsyncIterator[Any]:
        ws = await self._resolve()
        try:
            yield ws
        finally:
            await self._cleanup()


class WebSocketInterceptor:
    """Patches websockets.connect to intercept WebSocket connections."""

    def __init__(self) -> None:
        self._original_connect: Any = None

    def install(self) -> None:
        self._original_connect = websockets.asyncio.client.connect
        original_connect = self._original_connect

        def patched_connect(uri: str, **kwargs: Any) -> _PatchedConnect:
            return _PatchedConnect(original_connect, uri, kwargs)

        websockets.asyncio.client.connect = patched_connect  # type: ignore[assignment,misc]
        websockets.connect = patched_connect  # type: ignore[assignment,misc]

    def uninstall(self) -> None:
        if self._original_connect is not None:
            websockets.asyncio.client.connect = self._original_connect  # type: ignore[misc]
            websockets.connect = self._original_connect  # type: ignore[misc]


def extract_ws_headers(kwargs: dict[str, Any]) -> dict[str, list[str]]:
    extra = kwargs.get("additional_headers") or kwargs.get("extra_headers")
    if extra is None:
        return {}
    result: dict[str, list[str]] = {}
    items = extra.items() if isinstance(extra, dict) else extra
    for k, v in items:
        key = k.lower()
        values = [v] if isinstance(v, str) else list(v)
        result.setdefault(key, []).extend(values)
    return result


def frame_to_data(frame: WsFrame) -> str | bytes:
    body = frame.body
    if body.body_type == "binary":
        return body.content if isinstance(body.content, bytes) else b""
    if body.body_type == "text":
        return body.content if isinstance(body.content, str) else ""
    return ""
