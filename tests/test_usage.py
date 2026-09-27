from __future__ import annotations

from pathlib import Path

import grpc.aio
import pytest
import websockets

from cassetter import Body, Cassette, HttpResponse, WsFrame, use_cassette


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def recorded(tmp_path: Path) -> Path:
    path = tmp_path / "cassette.yaml"
    with use_cassette(path, record_mode="all", intercept=[]) as cassette:
        cassette.record("GET", "https://api.example.com/", {}, None, 200, {}, b"ok")
        cassette.record_grpc("/pkg.Svc/Call", {}, Body("binary", b"req"), Body("binary", b"resp"))
        cassette.record_ws("wss://ws.example.com/", {}, [WsFrame("recv", "text", Body("text", "hi"))])
    return path


@pytest.mark.anyio
async def test_all_played_counts_every_protocol(recorded: Path) -> None:
    with use_cassette(recorded, record_mode="none", intercept=["grpc", "websockets"]) as cassette:
        assert cassette.play("GET", "https://api.example.com/", {}, None) == HttpResponse(200, {}, Body("text", "ok"))
        assert cassette.played_indices == [True]
        assert (cassette.grpc_played_indices, cassette.ws_played_indices) == ([False], [False])
        assert not cassette.all_played

        async with grpc.aio.insecure_channel("localhost:1") as channel:
            assert await channel.unary_unary("/pkg.Svc/Call", bytes, bytes)(b"req") == b"resp"
        assert cassette.grpc_played_indices == [True]
        assert not cassette.all_played

        async with websockets.connect("wss://ws.example.com/") as ws:
            assert await ws.recv() == "hi"
        assert cassette.ws_played_indices == [True]
        assert cassette.all_played


def test_a_cassette_that_is_not_loaded_has_played_nothing(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "missing.yaml")
    assert (cassette.grpc_played_indices, cassette.ws_played_indices) == ([], [])
    assert cassette.all_played
