from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from websockets.asyncio.server import ServerConnection, serve


async def greet(ws: ServerConnection) -> None:
    await ws.recv()
    await ws.send("hello")
    await ws.send(b"\x00\x01")
    await ws.close(4000, "bye")


@pytest.fixture
async def ws_uri() -> AsyncIterator[str]:
    async with serve(greet, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}/"
