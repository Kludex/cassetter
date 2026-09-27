from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import websockets

import cassetter.websockets
from cassetter import use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


sdk = SimpleNamespace(ws_connect=websockets.connect)
"""Holds its own `connect` reference, taken before any cassette, as `google.genai.live` does."""


async def converse(uri: str) -> list[str | bytes]:
    async with sdk.ws_connect(uri) as ws:
        await ws.send("hi")
        return [await ws.recv(), await ws.recv()]


@pytest.mark.anyio
async def test_patching_an_imported_reference(tmp_path: Path, ws_uri: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk, "ws_connect", cassetter.websockets.connect)
    path = tmp_path / "ws.yaml"

    with use_cassette(path, record_mode="once", intercept=[]):
        assert await converse(ws_uri) == ["hello", b"\x00\x01"]

    with use_cassette(path, record_mode="none", intercept=[]) as cassette:
        assert await converse(ws_uri) == ["hello", b"\x00\x01"]
    assert cassette.ws_played_indices == [True]


@pytest.mark.anyio
async def test_connects_live_without_a_cassette(ws_uri: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk, "ws_connect", cassetter.websockets.connect)

    assert await converse(ws_uri) == ["hello", b"\x00\x01"]
