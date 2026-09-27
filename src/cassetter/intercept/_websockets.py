from __future__ import annotations

import asyncio
import struct
import time
from collections.abc import AsyncIterator, Generator
from typing import TYPE_CHECKING, Any, Literal

import websockets
import websockets.asyncio.client
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close, CloseCode

from cassetter._core import Body, WsFrame, WsInteraction
from cassetter._state import get_current_cassette
from cassetter.cassette import Cassette, NoMatchError

if TYPE_CHECKING:
    from typing_extensions import Buffer


class VCRWebSocket:
    """Wraps a real WebSocket connection to record sent/received frames."""

    def __init__(
        self,
        real_ws: Any,
        uri: str,
        headers: dict[str, list[str]],
        subprotocol: str | None = None,
    ) -> None:
        self._real = real_ws
        self._uri = uri
        self._headers = headers
        if subprotocol is not None:
            self._headers["sec-websocket-protocol"] = [subprotocol]
        self.subprotocol = subprotocol
        self._frames: list[WsFrame] = []
        self._terminal_recorded = False
        self._flushed = False
        self._start_time = time.monotonic()

    async def send(self, message: str | Buffer) -> None:
        self._frames.append(ws_frame("send", message, int((time.monotonic() - self._start_time) * 1000)))
        await self._real.send(message)

    async def recv(self, decode: bool | None = None) -> str | bytes:
        try:
            # Read undecoded, so the recorded frame type is the one on the wire.
            data: str | bytes = await self._real.recv()
        except websockets.exceptions.ConnectionClosed as exc:
            if not self._terminal_recorded:
                self._terminal_recorded = True
                close = exc.rcvd or Close(1006, "")
                content = struct.pack(">H", close.code) + close.reason.encode()
                offset_ms = int((time.monotonic() - self._start_time) * 1000)
                self._frames.append(WsFrame("recv", "close", Body("binary", content), offset_ms))
                self._flush()
            raise
        self._frames.append(ws_frame("recv", data, int((time.monotonic() - self._start_time) * 1000)))
        return decoded(data, decode)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self._real.close(code, reason)
        self._flush()

    @property
    def close_code(self) -> int | None:
        return self._real.close_code  # type: ignore[no-any-return]

    @property
    def close_reason(self) -> str | None:
        return self._real.close_reason  # type: ignore[no-any-return]

    def _flush(self) -> None:
        cassette = get_current_cassette()
        if not self._flushed and cassette is not None:
            cassette.record_ws(self._uri, self._headers, self._frames)
            self._frames = []
            self._flushed = True

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
    """Replays recorded WebSocket frames without a real connection.

    When `cassette` matches on `"body"`, every `send()` must match the next recorded send, and `recv()`
    waits until each send recorded before its frame has been made.
    """

    def __init__(self, interaction: WsInteraction, cassette: Cassette | None = None) -> None:
        self._uri = interaction.uri
        self._cassette = cassette if cassette is not None and "body" in cassette.match_config.match_on else None
        self._sends: list[WsFrame] = []
        self._recv_frames: list[WsFrame] = []
        # How many recorded sends precede each received frame, then the end of the conversation.
        self._sends_before: list[int] = []
        self._close: WsFrame | None = None
        for frame in interaction.frames:
            if frame.direction == "send":
                self._sends.append(frame)
            elif frame.frame_type == "close":
                self._close = frame
                break
            else:
                self._recv_frames.append(frame)
                self._sends_before.append(len(self._sends))
        self._sends_before.append(len(self._sends))
        self.subprotocol = next(
            (
                values[0]
                for name, values in interaction.headers.items()
                if name.lower() == "sec-websocket-protocol" and values
            ),
            None,
        )
        self._received = 0
        self._sent = 0
        self._progress = asyncio.Condition()
        self._closed: ConnectionClosed | None = None
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def send(self, message: str | Buffer) -> None:
        if self._closed is not None:
            raise self._closed
        if self._cassette is None:
            return
        actual = self._cassette._as_recorded(ws_frame("send", message))
        if actual is None:
            return
        position = f"WebSocket send #{self._sent + 1} to {self._uri}"
        if self._sent >= len(self._sends):
            raise NoMatchError(f"{position} is not in the recording, which has {len(self._sends)}")
        expected = self._sends[self._sent]
        if (actual.frame_type, actual.body) != (expected.frame_type, expected.body):
            raise NoMatchError(
                f"{position} does not match the recording\n"
                f"expected: {frame_to_data(expected)!r}\nactual: {frame_to_data(actual)!r}"
            )
        async with self._progress:
            self._sent += 1
            self._progress.notify_all()

    async def recv(self, decode: bool | None = None) -> str | bytes:
        async with self._progress:
            if self._cassette is not None:
                await self._progress.wait_for(self._may_receive)
            if self._closed is not None:
                raise self._closed
            if self._received >= len(self._recv_frames):
                if self._close is None:
                    # Recorded frames are exhausted; end the stream as a normal closure, the way a real
                    # connection does, so `await ws.recv()` callers see ConnectionClosed.
                    raise self._end(Close(CloseCode.NORMAL_CLOSURE, ""), None)
                content = self._close.body.content
                data = content if isinstance(content, bytes) else b""
                if len(data) < 2:
                    raise ValueError("recorded WebSocket close body is shorter than its status code")
                raise self._end(Close(struct.unpack(">H", data[:2])[0], data[2:].decode()), None)
            frame = self._recv_frames[self._received]
            self._received += 1
            return decoded(frame_to_data(frame), decode)

    @property
    def received_frames(self) -> list[WsFrame]:
        """Recorded frames `recv()` has returned, in order. Their `offset_ms` can drive a deterministic clock."""
        return self._recv_frames[: self._received]

    def _may_receive(self) -> bool:
        return self._closed is not None or self._sent >= self._sends_before[self._received]

    async def close(self, code: int = 1000, reason: str = "") -> None:
        async with self._progress:
            if self._closed is None:
                self._end(Close(code, reason), Close(code, reason))
        if self._cassette is not None and self._sent < len(self._sends):
            unsent = len(self._sends) - self._sent
            raise NoMatchError(f"WebSocket connection to {self._uri} closed with {unsent} recorded send(s) unsent")

    def _end(self, rcvd: Close, sent: Close | None) -> ConnectionClosed:
        self.close_code, self.close_reason = rcvd.code, rcvd.reason
        ok = rcvd.code in (CloseCode.NORMAL_CLOSURE, CloseCode.GOING_AWAY, CloseCode.NO_STATUS_RCVD)
        rcvd_then_sent = None if sent is None else False
        self._closed = (ConnectionClosedOK if ok else ConnectionClosedError)(rcvd, sent, rcvd_then_sent)
        self._progress.notify_all()
        return self._closed

    async def __aenter__(self) -> VCRWebSocketReplay:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, *args: object) -> None:
        try:
            await self.close()
        except NoMatchError:
            # Unsent frames are reported only when nothing else went wrong, so they never mask the real error.
            if exc_type is None:
                raise

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
            self._bypassed = await self._original_connect(self._uri, **self._kwargs)
            return self._bypassed

        try:
            interaction = cassette.play_ws(self._uri)
            self._ws = VCRWebSocketReplay(interaction, cassette)
            return self._ws
        except NoMatchError:
            if not cassette.can_record:
                raise

        conn = self._original_connect(self._uri, **self._kwargs)  # pragma: no cover
        real_ws = await conn  # pragma: no cover
        headers = extract_ws_headers(self._kwargs)  # pragma: no cover
        self._ws = VCRWebSocket(real_ws, self._uri, headers, real_ws.subprotocol)  # pragma: no cover
        return self._ws  # pragma: no cover

    async def _cleanup(self, exc_type: type[BaseException] | None = None) -> None:
        # Flush recorded frames / close the connection regardless of call style.
        if self._ws is not None:
            await self._ws.__aexit__(exc_type, None, None)
        elif self._bypassed is not None:
            await self._bypassed.close()

    def __await__(self) -> Generator[Any, None, Any]:
        return self._resolve().__await__()

    async def __aenter__(self) -> Any:
        return await self._resolve()

    async def __aexit__(self, exc_type: type[BaseException] | None, *args: object) -> None:
        await self._cleanup(exc_type)

    def __aiter__(self) -> Any:
        # `async for ws in connect(...)` yields one connection then cleans up in
        # the generator's finally - Python does not call __aexit__ on async-for
        # iterations, so recorded frames would otherwise never be flushed.
        return self._reconnect()

    async def _reconnect(self) -> AsyncIterator[Any]:
        ws = await self._resolve()
        try:
            yield ws
        except BaseException as exc:
            await self._cleanup(type(exc))
            raise
        await self._cleanup()


_live_connect = websockets.asyncio.client.connect


def connect(uri: str, **kwargs: Any) -> _PatchedConnect:
    """Drop-in for `websockets.connect` that records into, or replays from, the active cassette.

    Without an active cassette, or for a bypassed host, it opens a live connection.
    """
    return _PatchedConnect(_live_connect, uri, kwargs)


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


def ws_frame(direction: Literal["send", "recv"], data: str | Buffer, offset_ms: int = 0) -> WsFrame:
    if isinstance(data, str):
        return WsFrame(direction, "text", Body("text", data), offset_ms)
    return WsFrame(direction, "binary", Body("binary", bytes(data)), offset_ms)


def frame_to_data(frame: WsFrame) -> str | bytes:
    body = frame.body
    if body.body_type == "binary":
        return body.content if isinstance(body.content, bytes) else b""
    if body.body_type == "text":
        return body.content if isinstance(body.content, str) else ""
    return ""


def decoded(data: str | bytes, decode: bool | None) -> str | bytes:
    """Apply `recv(decode=...)` as `websockets` does: `False` keeps text as bytes, `True` decodes binary."""
    if decode is False and isinstance(data, str):
        return data.encode()
    if decode is True and isinstance(data, bytes):
        return data.decode()
    return data
