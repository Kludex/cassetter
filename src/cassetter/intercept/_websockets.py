from __future__ import annotations

import time
from typing import Any

import websockets
import websockets.asyncio.client

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
            raise StopAsyncIteration
        frame = self._recv_frames[self._recv_index]
        self._recv_index += 1
        return _frame_to_data(frame)

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
        except StopAsyncIteration:
            raise


class WebSocketInterceptor:
    """Patches websockets.connect to intercept WebSocket connections."""

    def __init__(self) -> None:
        self._original_connect: Any = None

    def install(self) -> None:
        self._original_connect = websockets.asyncio.client.connect
        original_connect = self._original_connect

        class PatchedConnect:
            def __init__(self, uri: str, **kwargs: Any) -> None:
                self._uri = uri
                self._kwargs = kwargs
                self._ws: VCRWebSocket | VCRWebSocketReplay | None = None

            async def __aenter__(self) -> VCRWebSocket | VCRWebSocketReplay:
                cassette = get_current_cassette()
                if cassette is None:
                    conn = original_connect(self._uri, **self._kwargs)  # pragma: no cover
                    return await conn.__aenter__()  # type: ignore[no-any-return]  # pragma: no cover

                try:
                    interaction = cassette.play_ws(self._uri)
                    self._ws = VCRWebSocketReplay(interaction)
                    return self._ws
                except NoMatchError:
                    if not cassette.can_record:
                        raise

                conn = original_connect(self._uri, **self._kwargs)  # pragma: no cover
                real_ws = await conn.__aenter__()  # pragma: no cover
                headers = _extract_ws_headers(self._kwargs)  # pragma: no cover
                self._ws = VCRWebSocket(real_ws, self._uri, headers)  # pragma: no cover
                return self._ws  # pragma: no cover

            async def __aexit__(self, *args: Any) -> None:
                if self._ws is not None:
                    await self._ws.__aexit__(*args)

        websockets.asyncio.client.connect = PatchedConnect  # type: ignore[assignment,misc]
        websockets.connect = PatchedConnect  # type: ignore[assignment,misc]

    def uninstall(self) -> None:
        if self._original_connect is not None:
            websockets.asyncio.client.connect = self._original_connect  # type: ignore[misc]
            websockets.connect = self._original_connect  # type: ignore[misc]


def _extract_ws_headers(kwargs: dict[str, Any]) -> dict[str, list[str]]:
    extra = kwargs.get("additional_headers") or kwargs.get("extra_headers")
    if extra is None:
        return {}
    result: dict[str, list[str]] = {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            result[k.lower()] = [v] if isinstance(v, str) else list(v)
    return result


def _frame_to_data(frame: WsFrame) -> str | bytes:
    body = frame.body
    if body.body_type == "binary":
        return body.content if isinstance(body.content, bytes) else b""
    if body.body_type == "text":
        return body.content if isinstance(body.content, str) else ""
    return ""
