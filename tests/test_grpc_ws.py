from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import grpc
import grpc.aio
import pytest
import websockets.asyncio.client
import websockets.exceptions
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close

from cassetter._core import (
    Body,
    Cassette as RustCassette,
    GrpcInteraction,
    GrpcRequest,
    GrpcResponse,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    WsFrame,
    WsInteraction,
    find_grpc_match,
    find_ws_match,
)
from cassetter._state import current_cassette
from cassetter.cassette import Cassette, NoMatchError
from cassetter.intercept._grpc import (
    GrpcInterceptor,
    VCRChannel,
    VCRStreamStreamCallable,
    VCRStreamUnaryCallable,
    VCRUnaryStreamCallable,
    VCRUnaryUnaryCallable,
    async_iter,
    build_json_debug,
    decode_chunks,
    encode_chunks,
    iter_bytes,
    metadata_to_dict,
    raise_for_status,
    replay_stream,
)
from cassetter.intercept._websockets import (
    VCRWebSocket,
    VCRWebSocketReplay,
    WebSocketInterceptor,
    _PatchedConnect,
    extract_ws_headers,
    frame_to_data,
)
from cassetter.recording import RecordMode

# --- gRPC types ---


def test_grpc_request_fields() -> None:
    req = GrpcRequest("/pkg.Svc/Method", {"x-id": ["abc"]}, Body("binary", b"\x0a\x0b"))
    assert req.method == "/pkg.Svc/Method"
    assert req.metadata == {"x-id": ["abc"]}
    assert req.body.body_type == "binary"


def test_grpc_response_fields() -> None:
    resp = GrpcResponse(0, "OK", {}, Body("binary", b"\x12\x03"))
    assert resp.status_code == 0
    assert resp.status_message == "OK"


def test_grpc_response_defaults() -> None:
    resp = GrpcResponse(0)
    assert resp.status_message == "OK"
    assert resp.metadata == {}
    assert resp.body.body_type == "none"


def test_grpc_interaction_recorded_at() -> None:
    req = GrpcRequest("/pkg.Svc/Method")
    resp = GrpcResponse(0)
    interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z")
    assert interaction.recorded_at == "2026-01-01T00:00:00Z"
    assert interaction.json_debug is None


def test_grpc_interaction_with_json_debug() -> None:
    req = GrpcRequest("/pkg.Svc/Method")
    resp = GrpcResponse(0)
    debug = {"request": {"input": "Hello"}, "response": {"output": "Hi"}}
    interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z", debug)
    assert interaction.json_debug == debug


def test_grpc_interaction_repr() -> None:
    req = GrpcRequest("/pkg.Svc/Method")
    resp = GrpcResponse(0)
    interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z")
    assert "/pkg.Svc/Method" in repr(interaction)


# --- WebSocket types ---


def test_ws_frame_fields() -> None:
    frame = WsFrame("send", "text", Body("text", "hello"), 0)
    assert frame.direction == "send"
    assert frame.frame_type == "text"
    assert frame.offset_ms == 0


def test_ws_frame_default_offset() -> None:
    frame = WsFrame("recv", "binary", Body("binary", b"\x00"))
    assert frame.offset_ms == 0


def test_ws_interaction_with_frames() -> None:
    frames = [
        WsFrame("send", "text", Body("text", '{"subscribe": "ticker"}'), 0),
        WsFrame("recv", "text", Body("text", '{"price": 42.5}'), 120),
    ]
    interaction = WsInteraction("wss://ws.example.com/stream", {}, frames)
    assert interaction.uri == "wss://ws.example.com/stream"
    assert len(interaction.frames) == 2


def test_ws_interaction_defaults() -> None:
    interaction = WsInteraction("wss://ws.example.com")
    assert interaction.headers == {}
    assert interaction.frames == []
    assert interaction.recorded_at == ""


# --- gRPC matching ---


def test_find_grpc_match_by_method() -> None:
    interactions = [
        GrpcInteraction(
            GrpcRequest("/pkg.Svc/MethodA"),
            GrpcResponse(0),
            "2026-01-01T00:00:00Z",
        ),
        GrpcInteraction(
            GrpcRequest("/pkg.Svc/MethodB"),
            GrpcResponse(0),
            "2026-01-01T00:00:00Z",
        ),
    ]
    result = find_grpc_match("/pkg.Svc/MethodB", interactions, [False, False])
    assert result is not None
    idx, interaction = result
    assert idx == 1
    assert interaction.request.method == "/pkg.Svc/MethodB"


def test_find_grpc_match_prefers_unplayed() -> None:
    interactions = [
        GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"),
        GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t2"),
    ]
    result = find_grpc_match("/pkg.Svc/M", interactions, [True, False])
    assert result is not None
    assert result[0] == 1


def test_find_grpc_match_falls_back_to_played() -> None:
    interactions = [
        GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"),
    ]
    result = find_grpc_match("/pkg.Svc/M", interactions, [True])
    assert result is not None
    assert result[0] == 0


def test_find_grpc_match_returns_none_on_no_match() -> None:
    interactions = [
        GrpcInteraction(GrpcRequest("/pkg.Svc/MethodA"), GrpcResponse(0), "t1"),
    ]
    assert find_grpc_match("/pkg.Svc/Unknown", interactions, [False]) is None


# --- WebSocket matching ---


def test_find_ws_match_by_uri() -> None:
    interactions = [
        WsInteraction("wss://a.example.com"),
        WsInteraction("wss://b.example.com"),
    ]
    result = find_ws_match("wss://b.example.com", interactions, [False, False])
    assert result is not None
    assert result[0] == 1


def test_find_ws_match_prefers_unplayed() -> None:
    interactions = [
        WsInteraction("wss://a.example.com"),
        WsInteraction("wss://a.example.com"),
    ]
    result = find_ws_match("wss://a.example.com", interactions, [True, False])
    assert result is not None
    assert result[0] == 1


def test_find_ws_match_returns_none_on_no_match() -> None:
    interactions = [WsInteraction("wss://a.example.com")]
    assert find_ws_match("wss://other.com", interactions, [False]) is None


# --- RustCassette gRPC/WS operations ---


def test_rust_cassette_add_grpc_interaction() -> None:
    c = RustCassette()
    c.add_grpc_interaction(GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"))
    assert len(c) == 1
    assert len(c.grpc_interactions) == 1
    assert c.grpc_played == [False]


def test_rust_cassette_mark_grpc_played() -> None:
    c = RustCassette()
    c.add_grpc_interaction(GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"))
    c.mark_grpc_played(0)
    assert c.grpc_played == [True]


def test_rust_cassette_mark_grpc_played_out_of_range() -> None:
    c = RustCassette()
    with pytest.raises(IndexError):
        c.mark_grpc_played(0)


def test_rust_cassette_add_ws_interaction() -> None:
    c = RustCassette()
    c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
    assert len(c) == 1
    assert len(c.ws_interactions) == 1
    assert c.ws_played == [False]


def test_rust_cassette_mark_ws_played() -> None:
    c = RustCassette()
    c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
    c.mark_ws_played(0)
    assert c.ws_played == [True]


def test_rust_cassette_mark_ws_played_out_of_range() -> None:
    c = RustCassette()
    with pytest.raises(IndexError):
        c.mark_ws_played(0)


def test_rust_cassette_len_mixed_protocols() -> None:
    c = RustCassette()
    c.add_interaction(HttpInteraction(HttpRequest("GET", "https://example.com"), HttpResponse(200), "t1"))
    c.add_grpc_interaction(GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"))
    c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
    assert len(c) == 3


def test_rust_cassette_repr_includes_grpc() -> None:
    c = RustCassette()
    c.add_grpc_interaction(GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"))
    assert "grpc=1" in repr(c)


# --- Cassette roundtrip (save/load) ---


def test_grpc_save_and_load(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "grpc.yaml")
    c = RustCassette()
    c.add_grpc_interaction(
        GrpcInteraction(
            GrpcRequest("/pkg.Svc/Method", {"x-id": ["abc"]}, Body("binary", b"\x0a\x0b")),
            GrpcResponse(0, "OK", {}, Body("binary", b"\x12\x03")),
            "2026-01-01T00:00:00Z",
            {"request": {"input": "Hello"}, "response": {"output": "Hi"}},
        )
    )
    c.save(path)

    with open(path) as f:
        content = f.read()
    assert "grpc_interactions" in content
    assert "/pkg.Svc/Method" in content
    assert "json_debug" in content

    c2 = RustCassette.load(path)
    assert len(c2.grpc_interactions) == 1
    grpc_i = c2.grpc_interactions[0]
    assert grpc_i.request.method == "/pkg.Svc/Method"
    assert grpc_i.response.status_code == 0
    assert grpc_i.request.body.body_type == "binary"
    assert grpc_i.json_debug == {"request": {"input": "Hello"}, "response": {"output": "Hi"}}


def test_ws_save_and_load(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws.yaml")
    c = RustCassette()
    c.add_ws_interaction(
        WsInteraction(
            "wss://ws.example.com/stream",
            {"sec-websocket-key": ["abc"]},
            [
                WsFrame("send", "text", Body("text", '{"subscribe": "ticker"}'), 0),
                WsFrame("recv", "text", Body("text", '{"price": 42.5}'), 120),
            ],
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)

    with open(path) as f:
        content = f.read()
    assert "ws_interactions" in content
    assert "wss://ws.example.com/stream" in content

    c2 = RustCassette.load(path)
    assert len(c2.ws_interactions) == 1
    ws_i = c2.ws_interactions[0]
    assert ws_i.uri == "wss://ws.example.com/stream"
    assert len(ws_i.frames) == 2
    assert ws_i.frames[0].direction == "send"
    assert ws_i.frames[1].offset_ms == 120


def test_mixed_protocol_roundtrip(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "mixed.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://api.example.com/users"),
            HttpResponse(200, body=Body("json", {"users": []})),
            "2026-01-01T00:00:00Z",
        )
    )
    c.add_grpc_interaction(
        GrpcInteraction(
            GrpcRequest("/pkg.Svc/Method"),
            GrpcResponse(0),
            "2026-01-01T00:00:00Z",
        )
    )
    c.add_ws_interaction(WsInteraction("wss://ws.example.com", recorded_at="2026-01-01T00:00:00Z"))
    c.save(path)

    c2 = RustCassette.load(path)
    assert len(c2.interactions) == 1
    assert len(c2.grpc_interactions) == 1
    assert len(c2.ws_interactions) == 1
    assert len(c2) == 3


def test_backward_compat_http_only(tmp_path: Path) -> None:
    """Existing HTTP-only cassettes still load without grpc/ws sections."""
    path = os.path.join(str(tmp_path), "http_only.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com/"),
            HttpResponse(200, body=Body("text", "ok")),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)

    # Verify no grpc/ws sections in the YAML
    with open(path) as f:
        content = f.read()
    assert "grpc_interactions" not in content
    assert "ws_interactions" not in content

    # Still loads fine
    c2 = RustCassette.load(path)
    assert len(c2.interactions) == 1
    assert len(c2.grpc_interactions) == 0
    assert len(c2.ws_interactions) == 0


# --- Cassette wrapper gRPC/WS ---


def test_grpc_and_ws_properties_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml")
    assert cassette.grpc_interactions == []
    assert cassette.ws_interactions == []


def test_play_grpc_before_load_raises() -> None:
    cassette = Cassette("/tmp/test.yaml")
    with pytest.raises(NoMatchError, match="cassette not loaded"):
        cassette.play_grpc("/pkg.Svc/Method")


def test_play_ws_before_load_raises() -> None:
    cassette = Cassette("/tmp/test.yaml")
    with pytest.raises(NoMatchError, match="cassette not loaded"):
        cassette.play_ws("wss://example.com")


def test_record_and_play_grpc(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "grpc_test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/Method",
        metadata={"x-id": ["abc"]},
        request_body=Body("binary", b"\x0a\x0b"),
        response_body=Body("binary", b"\x12\x03"),
    )
    assert len(cassette.grpc_interactions) == 1

    resp = cassette.play_grpc("/pkg.Svc/Method")
    assert resp.status_code == 0
    assert resp.body.body_type == "binary"


def test_play_grpc_no_match_raises(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    with pytest.raises(NoMatchError, match="no matching gRPC"):
        cassette.play_grpc("/pkg.Svc/Unknown")


def test_record_ws_interaction(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [
        WsFrame("send", "text", Body("text", "hello"), 0),
        WsFrame("recv", "text", Body("text", "world"), 50),
    ]
    cassette.record_ws("wss://ws.example.com", {}, frames)
    assert len(cassette.ws_interactions) == 1


def test_record_ws_scrubs_headers(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_scrub.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    headers = {"authorization": ["Bearer super-secret-token"], "x-custom": ["keep"]}
    cassette.record_ws("wss://ws.example.com", headers, [])

    recorded = cassette.ws_interactions[0]
    assert "authorization" not in recorded.headers
    assert recorded.headers["x-custom"] == ["keep"]


def test_record_ws_scrubs_uri_and_replays_live_uri(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_uri_scrub.yaml")
    uri = "wss://ws.example.com?access_token=super-secret-token"
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()
    cassette.record_ws(uri, {}, [])
    cassette.save()

    assert cassette.ws_interactions[0].uri.endswith("access_token=[FILTERED]")

    replayed = Cassette(path, record_mode=RecordMode.NONE)
    replayed.load()
    assert replayed.play_ws(uri).uri.endswith("access_token=[FILTERED]")


def test_record_ws_scrubs_frame_bodies(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_frame_scrub.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [
        WsFrame("send", "text", Body("json", {"access_token": "tok_abc", "channel": "ticker"}), 0),
        WsFrame("recv", "text", Body("text", '{"password": "secret", "ok": true}'), 10),
    ]
    cassette.record_ws("wss://ws.example.com", {}, frames)

    recorded = cassette.ws_interactions[0]
    assert recorded.frames[0].body.content["access_token"] == "[FILTERED]"
    assert recorded.frames[0].body.content["channel"] == "ticker"
    # A text frame that parses as JSON is scrubbed as a tree and re-serialized.
    assert '"password":"[FILTERED]"' in recorded.frames[1].body.content


def test_record_grpc_scrubs_metadata_and_json_debug(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "grpc_scrub.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/Login",
        metadata={"authorization": ["Bearer super-secret-token"], "x-custom": ["keep"]},
        request_body=Body("binary", b"\x0a\x0b"),
        response_body=Body("binary", b"\x12\x03"),
        response_metadata={"set-cookie": ["session=abc"]},
        json_debug={"request": {"password": "hunter2"}, "response": {"access_token": "tok"}},
    )

    recorded = cassette.grpc_interactions[0]
    assert "authorization" not in recorded.request.metadata
    assert recorded.request.metadata["x-custom"] == ["keep"]
    assert "set-cookie" not in recorded.response.metadata
    assert recorded.json_debug["request"]["password"] == "[FILTERED]"
    assert recorded.json_debug["response"]["access_token"] == "[FILTERED]"
    assert recorded.request.body.content == b"\x0a\x0b"


def test_record_grpc_scrubs_structured_bodies(tmp_path: Path) -> None:
    cassette = Cassette(os.path.join(str(tmp_path), "grpc_body_scrub.yaml"), record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/Login",
        metadata={},
        request_body=Body("json", {"api_key": "secret", "message": "hello"}),
        response_body=Body("text", '{"api-key":"secret","ok":true}'),
    )

    recorded = cassette.grpc_interactions[0]
    assert recorded.request.body.content == {"api_key": "[FILTERED]", "message": "hello"}
    assert '"api-key":"[FILTERED]"' in recorded.response.body.content


def test_play_ws_interaction(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_play.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [
        WsFrame("send", "text", Body("text", "hello"), 0),
        WsFrame("recv", "text", Body("text", "world"), 50),
    ]
    cassette.record_ws("wss://ws.example.com", {}, frames)

    interaction = cassette.play_ws("wss://ws.example.com")
    assert interaction.uri == "wss://ws.example.com"
    assert len(interaction.frames) == 2


def test_play_ws_no_match_raises(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "ws_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    with pytest.raises(NoMatchError, match="no matching WebSocket"):
        cassette.play_ws("wss://unknown.com")


def test_grpc_ws_save_persists(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "mixed_persist.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/M",
        metadata={},
        request_body=Body("binary", b"\x01"),
        response_body=Body("binary", b"\x02"),
    )
    cassette.record_ws("wss://ws.example.com", {}, [])
    cassette.save()

    cassette2 = Cassette(path, record_mode=RecordMode.NONE)
    cassette2.load()
    assert len(cassette2.grpc_interactions) == 1
    assert len(cassette2.ws_interactions) == 1


def test_record_grpc_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    resp = cassette.record_grpc(
        method="/pkg.Svc/M",
        metadata={},
        request_body=Body("binary", b"\x01"),
        response_body=Body("binary", b"\x02"),
    )
    assert resp.status_code == 0
    assert len(cassette.grpc_interactions) == 1


def test_record_ws_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    cassette.record_ws("wss://ws.example.com", {}, [])
    assert len(cassette.ws_interactions) == 1


# --- gRPC chunk encoding ---


def test_grpc_chunk_encode_decode_roundtrip() -> None:

    chunks = [b"hello", b"world", b"\x00\x01\x02"]
    encoded = encode_chunks(chunks)
    assert decode_chunks(encoded) == chunks


def test_grpc_chunk_encode_empty() -> None:

    assert encode_chunks([]) == b""
    assert decode_chunks(b"") == []


def test_grpc_chunk_encode_single() -> None:

    chunks = [b"\x0a\x0b"]
    encoded = encode_chunks(chunks)
    assert decode_chunks(encoded) == chunks


def test_grpc_chunk_decode_truncated() -> None:

    # Less than 4 bytes - can't read length
    assert decode_chunks(b"\x00\x01") == []


# --- gRPC interceptor helpers ---


def test_metadata_to_dict_none() -> None:

    assert metadata_to_dict(None) == {}


def test_metadata_to_dict_str_values() -> None:

    md = [("key1", "val1"), ("key2", "val2"), ("key1", "val1b")]
    result = metadata_to_dict(md)
    assert result == {"key1": ["val1", "val1b"], "key2": ["val2"]}


def test_metadata_to_dict_bytes_values() -> None:

    md = [("key", b"binary-val")]
    result = metadata_to_dict(md)
    assert result == {"key": ["binary-val"]}


def test_metadata_to_dict_binary_metadata() -> None:

    md = [("trace-bin", b"\xff\x00")]
    result = metadata_to_dict(md)
    assert result == {"trace-bin": ["/wA="]}


def test_build_json_debug_no_protobuf() -> None:

    # Objects without MessageToDict support return None
    result = build_json_debug("req", "resp")
    assert result is None


def test_build_json_debug_none_request() -> None:

    result = build_json_debug(None, "resp")
    assert result is None


@pytest.mark.anyio
async def testreplay_stream_chunked() -> None:

    chunks = [b"\x01", b"\x02\x03"]
    encoded = encode_chunks(chunks)
    resp = GrpcResponse(0, "OK", {}, Body("binary", encoded))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{b.hex()}"):
        results.append(item)
    assert results == ["got:01", "got:0203"]


@pytest.mark.anyio
async def testreplay_stream_single_fallback() -> None:

    # Non-chunked data: falls back to treating entire body as single message
    resp = GrpcResponse(0, "OK", {}, Body("binary", b"\x01\x02"))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{len(b)}"):
        results.append(item)
    assert results == ["got:2"]


@pytest.mark.anyio
async def testreplay_stream_empty_body() -> None:

    resp = GrpcResponse(0, "OK", {}, Body("none", b""))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{len(b)}"):
        results.append(item)
    assert results == ["got:0"]


def test_grpc_interceptor_install_uninstall() -> None:

    original_insecure = grpc.aio.insecure_channel
    original_secure = grpc.aio.secure_channel

    interceptor = GrpcInterceptor()

    interceptor.install()
    assert grpc.aio.insecure_channel is not original_insecure
    assert grpc.aio.secure_channel is not original_secure

    interceptor.uninstall()
    assert grpc.aio.insecure_channel is original_insecure
    assert grpc.aio.secure_channel is original_secure


@pytest.mark.anyio
async def test_unary_unary_replay(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_replay.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/Echo",
        metadata={},
        request_body=Body("binary", b"\x01"),
        response_body=Body("binary", b"\x02\x03"),
    )

    callable_ = VCRUnaryUnaryCallable(
        "/pkg.Svc/Echo",
        None,
        lambda x: b"\x01",
        lambda b: f"deserialized:{b.hex()}",
    )
    token = current_cassette.set(cassette)
    try:
        result = await callable_(object())
    finally:
        current_cassette.reset(token)
    assert result == "deserialized:0203"


@pytest.mark.anyio
async def test_unary_unary_no_match_raises(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    callable_ = VCRUnaryUnaryCallable(
        "/pkg.Svc/Unknown",
        None,
        lambda x: b"\x01",
        lambda b: b,
    )
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            await callable_(object())
    finally:
        current_cassette.reset(token)


@pytest.mark.anyio
async def test_unary_stream_replay(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_stream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    chunks = [b"\x01", b"\x02", b"\x03"]
    cassette.record_grpc(
        method="/pkg.Svc/Stream",
        metadata={},
        request_body=Body("binary", b"\x00"),
        response_body=Body("binary", encode_chunks(chunks)),
    )

    callable_ = VCRUnaryStreamCallable(
        "/pkg.Svc/Stream",
        None,
        lambda x: b"\x00",
        lambda b: f"chunk:{b.hex()}",
    )
    token = current_cassette.set(cassette)
    try:
        results = []
        async for item in callable_(object()):
            results.append(item)
    finally:
        current_cassette.reset(token)
    assert results == ["chunk:01", "chunk:02", "chunk:03"]


@pytest.mark.anyio
async def test_unary_stream_no_match_raises(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    callable_ = VCRUnaryStreamCallable("/pkg.Svc/X", None, lambda x: b"", lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            async for _ in callable_(object()):
                pass  # pragma: no cover
    finally:
        current_cassette.reset(token)


@pytest.mark.anyio
async def test_stream_unary_replay(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_cstream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record_grpc(
        method="/pkg.Svc/ClientStream",
        metadata={},
        request_body=Body("binary", b"\x00"),
        response_body=Body("binary", b"\xff"),
    )

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"
        yield b"\x02"

    callable_ = VCRStreamUnaryCallable(
        "/pkg.Svc/ClientStream",
        None,
        lambda x: x,  # identity serializer
        lambda b: f"resp:{b.hex()}",
    )
    token = current_cassette.set(cassette)
    try:
        result = await callable_(request_iter())
    finally:
        current_cassette.reset(token)
    assert result == "resp:ff"


@pytest.mark.anyio
async def test_stream_unary_no_match_raises(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"

    callable_ = VCRStreamUnaryCallable("/pkg.Svc/X", None, lambda x: x, lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            await callable_(request_iter())
    finally:
        current_cassette.reset(token)


@pytest.mark.anyio
async def test_stream_stream_replay(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_bidi.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    resp_chunks = [b"\x0a", b"\x0b"]
    cassette.record_grpc(
        method="/pkg.Svc/Bidi",
        metadata={},
        request_body=Body("binary", b"\x00"),
        response_body=Body("binary", encode_chunks(resp_chunks)),
    )

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # pragma: no cover

    callable_ = VCRStreamStreamCallable(
        "/pkg.Svc/Bidi",
        None,
        lambda x: x,
        lambda b: f"got:{b.hex()}",
    )
    token = current_cassette.set(cassette)
    try:
        results = []
        async for item in callable_(request_iter()):
            results.append(item)
    finally:
        current_cassette.reset(token)
    assert results == ["got:0a", "got:0b"]


@pytest.mark.anyio
async def test_stream_stream_no_match_raises(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # pragma: no cover

    callable_ = VCRStreamStreamCallable("/pkg.Svc/X", None, lambda x: x, lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            async for _ in callable_(request_iter()):
                pass  # pragma: no cover
    finally:
        current_cassette.reset(token)


# --- WebSocket interceptor helpers ---


def test_frame_to_data_text() -> None:

    frame = WsFrame("recv", "text", Body("text", "hello"), 0)
    assert frame_to_data(frame) == "hello"


def test_frame_to_data_binary() -> None:

    frame = WsFrame("recv", "binary", Body("binary", b"\x01\x02"), 0)
    assert frame_to_data(frame) == b"\x01\x02"


def test_frame_to_data_none_body() -> None:

    frame = WsFrame("recv", "text", Body("none", b""), 0)
    assert frame_to_data(frame) == ""


def test_extract_ws_headers_empty() -> None:

    assert extract_ws_headers({}) == {}


def test_extract_ws_headers_additional() -> None:

    result = extract_ws_headers({"additional_headers": {"Authorization": "Bearer tok"}})
    assert result == {"authorization": ["Bearer tok"]}


def test_extract_ws_headers_extra() -> None:

    result = extract_ws_headers({"extra_headers": {"X-Key": "val"}})
    assert result == {"x-key": ["val"]}


@pytest.mark.anyio
async def test_replay_ws_recv() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {"sec-websocket-protocol": ["chat"]},
        [
            WsFrame("send", "text", Body("text", "ping"), 0),
            WsFrame("recv", "text", Body("text", "pong"), 10),
            WsFrame("recv", "text", Body("text", "data"), 20),
        ],
    )
    ws = VCRWebSocketReplay(interaction)
    assert ws.subprotocol == "chat"
    assert await ws.recv() == "pong"
    assert await ws.recv() == "data"
    # Exhausted replay signals a clean close, like a real connection at EOF

    with pytest.raises(ConnectionClosedOK):
        await ws.recv()


@pytest.mark.anyio
async def test_replay_ws_close_status() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [WsFrame("recv", "close", Body("binary", b"\x03\xf0denied"), 10)],
    )
    ws = VCRWebSocketReplay(interaction)
    with pytest.raises(ConnectionClosedError) as exc_info:
        await ws.recv()
    assert exc_info.value.rcvd == Close(1008, "denied")


@pytest.mark.anyio
async def test_replay_ws_normal_close_status() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [WsFrame("recv", "close", Body("binary", b"\x03\xe8done"), 10)],
    )
    ws = VCRWebSocketReplay(interaction)
    with pytest.raises(ConnectionClosedOK) as exc_info:
        await ws.recv()
    assert exc_info.value.rcvd == Close(1000, "done")


@pytest.mark.anyio
async def test_replay_ws_rejects_short_close_frame() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [WsFrame("recv", "close", Body("binary", b"\x03"), 10)],
    )
    ws = VCRWebSocketReplay(interaction)
    with pytest.raises(ValueError, match="shorter than its status code"):
        await ws.recv()


@pytest.mark.anyio
async def test_replay_ws_send_is_noop() -> None:

    interaction = WsInteraction("wss://ws.example.com", {}, [])
    ws = VCRWebSocketReplay(interaction)
    await ws.send("ignored")  # should not raise


@pytest.mark.anyio
async def test_replay_ws_close_is_noop() -> None:

    interaction = WsInteraction("wss://ws.example.com", {}, [])
    ws = VCRWebSocketReplay(interaction)
    await ws.close()  # should not raise


@pytest.mark.anyio
async def test_replay_ws_context_manager() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [WsFrame("recv", "text", Body("text", "hello"), 0)],
    )
    async with VCRWebSocketReplay(interaction) as ws:
        data = await ws.recv()
    assert data == "hello"


@pytest.mark.anyio
async def test_replay_wsasync_iter() -> None:

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [
            WsFrame("recv", "text", Body("text", "a"), 0),
            WsFrame("recv", "text", Body("text", "b"), 10),
        ],
    )
    ws = VCRWebSocketReplay(interaction)
    results = [item async for item in ws]
    assert results == ["a", "b"]


@pytest.mark.anyio
async def test_record_ws_frames(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_record.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def send(self, msg: str | bytes) -> None:
            pass

        async def recv(self) -> str:
            return "response"

        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {}, "chat")
        assert ws.subprotocol == "chat"
        await ws.send("hello")
        data = await ws.recv()
        assert data == "response"
        await ws.close()
    finally:
        current_cassette.reset(token)

    assert len(cassette.ws_interactions) == 1
    interaction = cassette.ws_interactions[0]
    assert len(interaction.frames) == 2
    assert interaction.frames[0].direction == "send"
    assert interaction.frames[1].direction == "recv"
    assert interaction.headers["sec-websocket-protocol"] == ["chat"]


@pytest.mark.anyio
async def test_record_ws_close_status(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_close.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def recv(self) -> str:
            raise ConnectionClosedError(Close(1008, "denied"), None)

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
        with pytest.raises(ConnectionClosedError):
            await ws.recv()
        with pytest.raises(ConnectionClosedError):
            await ws.recv()
    finally:
        current_cassette.reset(token)

    assert len(cassette.ws_interactions) == 1
    frame = cassette.ws_interactions[0].frames[0]
    assert frame.direction == "recv"
    assert frame.frame_type == "close"
    assert frame.body.content == b"\x03\xf0denied"


@pytest.mark.anyio
async def test_record_ws_abnormal_close(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_abnormal.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def recv(self) -> str:
            raise ConnectionClosedError(None, None)

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
        with pytest.raises(ConnectionClosedError):
            await ws.recv()
    finally:
        current_cassette.reset(token)

    frame = cassette.ws_interactions[0].frames[0]
    assert frame.frame_type == "close"
    assert frame.body.content == b"\x03\xee"


@pytest.mark.anyio
async def test_record_ws_empty_connection(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {}, "chat")
        await ws.close()
    finally:
        current_cassette.reset(token)

    interaction = cassette.ws_interactions[0]
    assert interaction.frames == []
    assert interaction.headers["sec-websocket-protocol"] == ["chat"]


@pytest.mark.anyio
async def test_record_ws_context_manager(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_ctx.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def send(self, msg: str | bytes) -> None:
            pass

        async def recv(self) -> str:
            return "msg"

        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass

    real_ws = FakeWs()
    token = current_cassette.set(cassette)
    try:
        async with VCRWebSocket(real_ws, "wss://ws.example.com", {}) as ws:
            await ws.send("x")
            await ws.recv()
    finally:
        current_cassette.reset(token)

    assert len(cassette.ws_interactions) == 1


@pytest.mark.anyio
async def test_record_ws_binary_frames(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_binary.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        async def send(self, msg: str | bytes) -> None:
            pass

        async def recv(self) -> bytes:
            return b"\x01\x02\x03"

        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
        await ws.send(b"\xff\xfe")
        data = await ws.recv()
        assert data == b"\x01\x02\x03"
        await ws.close()
    finally:
        current_cassette.reset(token)

    interaction = cassette.ws_interactions[0]
    assert interaction.frames[0].frame_type == "binary"
    assert interaction.frames[1].frame_type == "binary"


@pytest.mark.anyio
async def test_record_wsasync_iter(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_iter.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        def __init__(self) -> None:
            self._msgs = ["a", "b"]
            self._idx = 0

        async def send(self, msg: str | bytes) -> None:
            pass  # pragma: no cover

        async def recv(self) -> str:
            if self._idx >= len(self._msgs):
                raise websockets.exceptions.ConnectionClosed(None, None)
            msg = self._msgs[self._idx]
            self._idx += 1
            return msg

        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass  # pragma: no cover

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
        results = [item async for item in ws]
    finally:
        current_cassette.reset(token)
    assert results == ["a", "b"]
    assert len(cassette.ws_interactions) == 1


@pytest.mark.anyio
async def test_patched_connect_replay(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_connect.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [WsFrame("recv", "text", Body("text", "hello"), 0)]
    cassette.record_ws("wss://ws.example.com/path", {}, frames)

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        async with websockets.asyncio.client.connect("wss://ws.example.com/path") as ws:
            data = await ws.recv()
            assert data == "hello"
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


@pytest.mark.anyio
async def test_patched_connect_no_match_raises(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "ws_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            async with websockets.asyncio.client.connect("wss://ws.example.com/unknown"):
                pass  # pragma: no cover
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


def test_websocket_interceptor_install_uninstall() -> None:

    original = websockets.asyncio.client.connect

    interceptor = WebSocketInterceptor()

    interceptor.install()
    assert websockets.asyncio.client.connect is not original

    interceptor.uninstall()
    assert websockets.asyncio.client.connect is original


# --- gRPC recording ---


@pytest.mark.anyio
async def test_unary_unary_record(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_rec.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeResponse:
        def SerializeToString(self) -> bytes:
            return b"\x02\x03"

    async def fake_call(request: object, **kwargs: object) -> FakeResponse:
        return FakeResponse()

    callable_ = VCRUnaryUnaryCallable(
        "/pkg.Svc/Echo",
        fake_call,
        lambda x: b"\x01",
        lambda b: b,
    )
    token = current_cassette.set(cassette)
    try:
        result = await callable_(object())
    finally:
        current_cassette.reset(token)
    assert isinstance(result, FakeResponse)
    assert len(cassette.grpc_interactions) == 1
    assert cassette.grpc_interactions[0].request.method == "/pkg.Svc/Echo"


@pytest.mark.anyio
async def test_unary_stream_record(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_rec_stream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeChunk:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def SerializeToString(self) -> bytes:
            return self._data

    async def fake_stream(*args: object, **kwargs: object) -> AsyncIterator[FakeChunk]:
        yield FakeChunk(b"\x0a")
        yield FakeChunk(b"\x0b")

    callable_ = VCRUnaryStreamCallable(
        "/pkg.Svc/Stream",
        fake_stream,
        lambda x: b"\x01",
        lambda b: b,
    )
    token = current_cassette.set(cassette)
    try:
        results = []
        async for item in callable_(object()):
            results.append(item)
    finally:
        current_cassette.reset(token)
    assert len(results) == 2
    assert len(cassette.grpc_interactions) == 1
    # Verify chunks were encoded
    body = cassette.grpc_interactions[0].response.body
    assert isinstance(body.content, bytes)
    chunks = decode_chunks(body.content)
    assert chunks == [b"\x0a", b"\x0b"]


@pytest.mark.anyio
async def test_stream_unary_record(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_rec_cstream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeResponse:
        def SerializeToString(self) -> bytes:
            return b"\xff"

    async def fake_call(request_iter: object, **kwargs: object) -> FakeResponse:
        return FakeResponse()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"
        yield b"\x02"

    callable_ = VCRStreamUnaryCallable(
        "/pkg.Svc/ClientStream",
        fake_call,
        lambda x: x,
        lambda b: b,
    )
    token = current_cassette.set(cassette)
    try:
        result = await callable_(request_iter())
    finally:
        current_cassette.reset(token)
    assert isinstance(result, FakeResponse)
    assert len(cassette.grpc_interactions) == 1


@pytest.mark.anyio
async def test_stream_stream_record(tmp_path: Path) -> None:

    path = os.path.join(str(tmp_path), "grpc_rec_bidi.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeChunk:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def SerializeToString(self) -> bytes:
            return self._data

    async def fake_bidi(request_iter: object, **kwargs: object) -> AsyncIterator[FakeChunk]:
        yield FakeChunk(b"\x0a")
        yield FakeChunk(b"\x0b")

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"

    callable_ = VCRStreamStreamCallable(
        "/pkg.Svc/Bidi",
        fake_bidi,
        lambda x: x,
        lambda b: b,
    )
    token = current_cassette.set(cassette)
    try:
        results = []
        async for item in callable_(request_iter()):
            results.append(item)
    finally:
        current_cassette.reset(token)
    assert len(results) == 2
    assert len(cassette.grpc_interactions) == 1
    body = cassette.grpc_interactions[0].response.body
    assert isinstance(body.content, bytes)
    chunks = decode_chunks(body.content)
    assert chunks == [b"\x0a", b"\x0b"]


# --- VCRChannel ---


def test_vcr_channel_wraps_methods() -> None:

    class FakeChannel:
        def unary_unary(self, method: str, *args: object) -> str:
            return "uu"

        def unary_stream(self, method: str, *args: object) -> str:
            return "us"

        def stream_unary(self, method: str, *args: object) -> str:
            return "su"

        def stream_stream(self, method: str, *args: object) -> str:
            return "ss"

        def other_method(self) -> str:
            return "other"

    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    cassette.load()

    channel = VCRChannel(FakeChannel())
    assert isinstance(channel.unary_unary("/m"), VCRUnaryUnaryCallable)
    assert isinstance(channel.unary_stream("/m"), VCRUnaryStreamCallable)
    assert isinstance(channel.stream_unary("/m"), VCRStreamUnaryCallable)
    assert isinstance(channel.stream_stream("/m"), VCRStreamStreamCallable)
    assert channel.other_method() == "other"  # __getattr__ delegation


@pytest.mark.anyio
async def test_vcr_channel_close() -> None:

    class FakeChannel:
        closed = False

        async def close(self) -> None:
            self.closed = True

    fake = FakeChannel()
    channel = VCRChannel(fake)
    await channel.close()
    assert fake.closed


@pytest.mark.anyio
async def test_vcr_channel_context_manager() -> None:

    class FakeChannel:
        entered = False
        exited = False

        async def __aenter__(self) -> FakeChannel:
            self.entered = True
            return self

        async def __aexit__(self, *args: object) -> None:
            self.exited = True

        async def close(self) -> None:
            pass  # pragma: no cover

    fake = FakeChannel()
    channel = VCRChannel(fake)

    async with channel as ch:
        assert ch is channel
    assert fake.entered
    assert fake.exited


# --- gRPC interceptor patching ---


def test_patched_channels_create_vcr_channels() -> None:

    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    cassette.load()

    interceptor = GrpcInterceptor()
    interceptor.install()
    try:
        # Verify the patched function returns VCRChannel

        patched_fn = grpc.aio.insecure_channel
        assert patched_fn is not interceptor._original_insecure
    finally:
        interceptor.uninstall()


# --- gRPC async helpers ---


@pytest.mark.anyio
async def test_grpcasync_iter() -> None:

    results = [item async for item in async_iter([b"\x01", b"\x02"])]
    assert results == [b"\x01", b"\x02"]


def test_grpciter_bytes() -> None:

    result = iter_bytes([b"\x01"], lambda b: b)
    assert result is not None


@pytest.mark.anyio
async def test_grpc_replay_error_status_raises() -> None:
    """A recorded non-OK gRPC status must replay as AioRpcError, not a success."""

    resp = GrpcResponse(5, "not found", {}, Body("binary", b""))
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        raise_for_status(resp)
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND
    assert exc_info.value.details() == "not found"


@pytest.mark.anyio
async def test_grpc_replay_ok_status_does_not_raise() -> None:

    raise_for_status(GrpcResponse(0, "OK", {}, Body("binary", b"")))


@pytest.mark.anyio
async def test_grpc_replay_stream_error_status_raises() -> None:

    resp = GrpcResponse(7, "permission denied", {}, Body("binary", b""))
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in replay_stream(resp, lambda b: b):
            pass  # pragma: no cover
    assert exc_info.value.code() == grpc.StatusCode.PERMISSION_DENIED


@pytest.mark.anyio
async def test_grpc_replay_unknown_status_code_maps_to_unknown() -> None:

    resp = GrpcResponse(999, "weird", {}, Body("binary", b""))
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        raise_for_status(resp)
    assert exc_info.value.code() == grpc.StatusCode.UNKNOWN


@pytest.mark.anyio
async def test_patched_connect_await_form(tmp_path: Path) -> None:
    """`ws = await websockets.connect(uri)` (not just `async with`) must work."""

    path = os.path.join(str(tmp_path), "ws_await.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()
    cassette.record_ws("wss://ws.example.com/p", {}, [WsFrame("recv", "text", Body("text", "hi"), 0)])

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        ws = await websockets.asyncio.client.connect("wss://ws.example.com/p")
        assert await ws.recv() == "hi"
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


@pytest.mark.anyio
async def test_patched_connect_async_for_form(tmp_path: Path) -> None:
    """`async for ws in connect(...)` reconnect loop yields one connection."""

    path = os.path.join(str(tmp_path), "ws_for.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()
    cassette.record_ws("wss://ws.example.com/p", {}, [WsFrame("recv", "text", Body("text", "yo"), 0)])

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        seen = []
        # Loop to completion (no break) so the reconnect iterator raises
        # StopAsyncIteration after yielding its single connection.
        async for ws in websockets.asyncio.client.connect("wss://ws.example.com/p"):
            seen.append(await ws.recv())
        assert seen == ["yo"]
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


@pytest.mark.anyio
async def test_ws_bypass_ignores_localhost(tmp_path: Path) -> None:
    """A bypassed WS URI must not consult the cassette (would raise NoMatch here)."""

    path = os.path.join(str(tmp_path), "ws_bypass.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE, ignore_localhost=True)
    cassette.load()

    sentinel = object()

    async def fake_original(uri: str, **kwargs: object) -> object:
        return sentinel

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        conn = _PatchedConnect(fake_original, "ws://localhost:1234/x", {})
        result = await conn
        assert result is sentinel
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


def test_extract_ws_headers_list_of_tuples() -> None:

    headers = extract_ws_headers({"additional_headers": [("Authorization", "Bearer x"), ("X-Trace", "1")]})
    assert headers == {"authorization": ["Bearer x"], "x-trace": ["1"]}
