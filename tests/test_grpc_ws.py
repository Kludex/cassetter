from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

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


def test_grpc_save_and_load(tmp_path: object) -> None:
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


def test_ws_save_and_load(tmp_path: object) -> None:
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


def test_mixed_protocol_roundtrip(tmp_path: object) -> None:
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


def test_backward_compat_http_only(tmp_path: object) -> None:
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


def test_record_and_play_grpc(tmp_path: object) -> None:
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


def test_play_grpc_no_match_raises(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    with pytest.raises(NoMatchError, match="no matching gRPC"):
        cassette.play_grpc("/pkg.Svc/Unknown")


def test_record_ws_interaction(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "ws_test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [
        WsFrame("send", "text", Body("text", "hello"), 0),
        WsFrame("recv", "text", Body("text", "world"), 50),
    ]
    cassette.record_ws("wss://ws.example.com", {}, frames)
    assert len(cassette.ws_interactions) == 1


def test_record_ws_scrubs_headers(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "ws_scrub.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    headers = {"authorization": ["Bearer super-secret-token"], "x-custom": ["keep"]}
    cassette.record_ws("wss://ws.example.com", headers, [])

    recorded = cassette.ws_interactions[0]
    assert "authorization" not in recorded.headers
    assert recorded.headers["x-custom"] == ["keep"]


def test_play_ws_interaction(tmp_path: object) -> None:
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


def test_play_ws_no_match_raises(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "ws_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    with pytest.raises(NoMatchError, match="no matching WebSocket"):
        cassette.play_ws("wss://unknown.com")


def test_grpc_ws_save_persists(tmp_path: object) -> None:
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
    from cassetter.intercept._grpc import decode_chunks, encode_chunks

    chunks = [b"hello", b"world", b"\x00\x01\x02"]
    encoded = encode_chunks(chunks)
    assert decode_chunks(encoded) == chunks


def test_grpc_chunk_encode_empty() -> None:
    from cassetter.intercept._grpc import decode_chunks, encode_chunks

    assert encode_chunks([]) == b""
    assert decode_chunks(b"") == []


def test_grpc_chunk_encode_single() -> None:
    from cassetter.intercept._grpc import decode_chunks, encode_chunks

    chunks = [b"\x0a\x0b"]
    encoded = encode_chunks(chunks)
    assert decode_chunks(encoded) == chunks


def test_grpc_chunk_decode_truncated() -> None:
    from cassetter.intercept._grpc import decode_chunks

    # Less than 4 bytes - can't read length
    assert decode_chunks(b"\x00\x01") == []


# --- gRPC interceptor helpers ---


def testmetadata_to_dict_none() -> None:
    from cassetter.intercept._grpc import metadata_to_dict

    assert metadata_to_dict(None) == {}


def testmetadata_to_dict_str_values() -> None:
    from cassetter.intercept._grpc import metadata_to_dict

    md = [("key1", "val1"), ("key2", "val2"), ("key1", "val1b")]
    result = metadata_to_dict(md)
    assert result == {"key1": ["val1", "val1b"], "key2": ["val2"]}


def testmetadata_to_dict_bytes_values() -> None:
    from cassetter.intercept._grpc import metadata_to_dict

    md = [("key", b"binary-val")]
    result = metadata_to_dict(md)
    assert result == {"key": ["binary-val"]}


def testbuild_json_debug_no_protobuf() -> None:
    from cassetter.intercept._grpc import build_json_debug

    # Objects without MessageToDict support return None
    result = build_json_debug("req", "resp")
    assert result is None


def testbuild_json_debug_none_request() -> None:
    from cassetter.intercept._grpc import build_json_debug

    result = build_json_debug(None, "resp")
    assert result is None


@pytest.mark.anyio
async def testreplay_stream_chunked() -> None:
    from cassetter.intercept._grpc import encode_chunks, replay_stream

    chunks = [b"\x01", b"\x02\x03"]
    encoded = encode_chunks(chunks)
    resp = GrpcResponse(0, "OK", {}, Body("binary", encoded))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{b.hex()}"):
        results.append(item)
    assert results == ["got:01", "got:0203"]


@pytest.mark.anyio
async def testreplay_stream_single_fallback() -> None:
    from cassetter.intercept._grpc import replay_stream

    # Non-chunked data: falls back to treating entire body as single message
    resp = GrpcResponse(0, "OK", {}, Body("binary", b"\x01\x02"))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{len(b)}"):
        results.append(item)
    assert results == ["got:2"]


@pytest.mark.anyio
async def testreplay_stream_empty_body() -> None:
    from cassetter.intercept._grpc import replay_stream

    resp = GrpcResponse(0, "OK", {}, Body("none", b""))
    results = []
    async for item in replay_stream(resp, lambda b: f"got:{len(b)}"):
        results.append(item)
    assert results == ["got:0"]


def test_grpc_interceptor_install_uninstall() -> None:
    import grpc.aio

    from cassetter.intercept._grpc import GrpcInterceptor

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
async def test_unary_unary_replay(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryUnaryCallable

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
async def test_unary_unary_no_match_raises(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryUnaryCallable

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
async def test_unary_stream_replay(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryStreamCallable, encode_chunks

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
async def test_unary_stream_no_match_raises(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryStreamCallable

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    callable_ = VCRUnaryStreamCallable("/pkg.Svc/X", None, lambda x: b"", lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            async for _ in callable_(object()):
                pass
    finally:
        current_cassette.reset(token)


@pytest.mark.anyio
async def test_stream_unary_replay(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamUnaryCallable

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
        yield b"\x01"  # type: ignore[misc]
        yield b"\x02"  # type: ignore[misc]

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
async def test_stream_unary_no_match_raises(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamUnaryCallable

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # type: ignore[misc]

    callable_ = VCRStreamUnaryCallable("/pkg.Svc/X", None, lambda x: x, lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            await callable_(request_iter())
    finally:
        current_cassette.reset(token)


@pytest.mark.anyio
async def test_stream_stream_replay(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamStreamCallable, encode_chunks

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
        yield b"\x01"  # type: ignore[misc]

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
async def test_stream_stream_no_match_raises(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamStreamCallable

    path = os.path.join(str(tmp_path), "grpc_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # type: ignore[misc]

    callable_ = VCRStreamStreamCallable("/pkg.Svc/X", None, lambda x: x, lambda b: b)
    token = current_cassette.set(cassette)
    try:
        with pytest.raises(NoMatchError):
            async for _ in callable_(request_iter()):
                pass
    finally:
        current_cassette.reset(token)


# --- WebSocket interceptor helpers ---


def testframe_to_data_text() -> None:
    from cassetter.intercept._websockets import frame_to_data

    frame = WsFrame("recv", "text", Body("text", "hello"), 0)
    assert frame_to_data(frame) == "hello"


def testframe_to_data_binary() -> None:
    from cassetter.intercept._websockets import frame_to_data

    frame = WsFrame("recv", "binary", Body("binary", b"\x01\x02"), 0)
    assert frame_to_data(frame) == b"\x01\x02"


def testframe_to_data_none_body() -> None:
    from cassetter.intercept._websockets import frame_to_data

    frame = WsFrame("recv", "text", Body("none", b""), 0)
    assert frame_to_data(frame) == ""


def testextract_ws_headers_empty() -> None:
    from cassetter.intercept._websockets import extract_ws_headers

    assert extract_ws_headers({}) == {}


def testextract_ws_headers_additional() -> None:
    from cassetter.intercept._websockets import extract_ws_headers

    result = extract_ws_headers({"additional_headers": {"Authorization": "Bearer tok"}})
    assert result == {"authorization": ["Bearer tok"]}


def testextract_ws_headers_extra() -> None:
    from cassetter.intercept._websockets import extract_ws_headers

    result = extract_ws_headers({"extra_headers": {"X-Key": "val"}})
    assert result == {"x-key": ["val"]}


@pytest.mark.anyio
async def test_replay_ws_recv() -> None:
    from cassetter.intercept._websockets import VCRWebSocketReplay

    interaction = WsInteraction(
        "wss://ws.example.com",
        {},
        [
            WsFrame("send", "text", Body("text", "ping"), 0),
            WsFrame("recv", "text", Body("text", "pong"), 10),
            WsFrame("recv", "text", Body("text", "data"), 20),
        ],
    )
    ws = VCRWebSocketReplay(interaction)
    assert await ws.recv() == "pong"
    assert await ws.recv() == "data"
    with pytest.raises(StopAsyncIteration):
        await ws.recv()


@pytest.mark.anyio
async def test_replay_ws_send_is_noop() -> None:
    from cassetter.intercept._websockets import VCRWebSocketReplay

    interaction = WsInteraction("wss://ws.example.com", {}, [])
    ws = VCRWebSocketReplay(interaction)
    await ws.send("ignored")  # should not raise


@pytest.mark.anyio
async def test_replay_ws_close_is_noop() -> None:
    from cassetter.intercept._websockets import VCRWebSocketReplay

    interaction = WsInteraction("wss://ws.example.com", {}, [])
    ws = VCRWebSocketReplay(interaction)
    await ws.close()  # should not raise


@pytest.mark.anyio
async def test_replay_ws_context_manager() -> None:
    from cassetter.intercept._websockets import VCRWebSocketReplay

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
    from cassetter.intercept._websockets import VCRWebSocketReplay

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
async def test_record_ws_frames(tmp_path: object) -> None:
    from cassetter.intercept._websockets import VCRWebSocket

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
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
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


@pytest.mark.anyio
async def test_record_ws_context_manager(tmp_path: object) -> None:
    from cassetter.intercept._websockets import VCRWebSocket

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
async def test_record_ws_binary_frames(tmp_path: object) -> None:
    from cassetter.intercept._websockets import VCRWebSocket

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
async def test_record_wsasync_iter(tmp_path: object) -> None:
    from cassetter.intercept._websockets import VCRWebSocket

    path = os.path.join(str(tmp_path), "ws_iter.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeWs:
        def __init__(self) -> None:
            self._msgs = ["a", "b"]
            self._idx = 0

        async def send(self, msg: str | bytes) -> None:
            pass

        async def recv(self) -> str:
            if self._idx >= len(self._msgs):
                import websockets.exceptions

                raise websockets.exceptions.ConnectionClosed(None, None)
            msg = self._msgs[self._idx]
            self._idx += 1
            return msg

        async def close(self, code: int = 1000, reason: str = "") -> None:
            pass

    token = current_cassette.set(cassette)
    try:
        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {})
        results = [item async for item in ws]
    finally:
        current_cassette.reset(token)
    assert results == ["a", "b"]
    assert len(cassette.ws_interactions) == 1


@pytest.mark.anyio
async def test_patched_connect_replay(tmp_path: object) -> None:
    from cassetter.intercept._websockets import WebSocketInterceptor

    path = os.path.join(str(tmp_path), "ws_connect.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    frames = [WsFrame("recv", "text", Body("text", "hello"), 0)]
    cassette.record_ws("wss://ws.example.com/path", {}, frames)

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        import websockets.asyncio.client

        async with websockets.asyncio.client.connect("wss://ws.example.com/path") as ws:
            data = await ws.recv()
            assert data == "hello"
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


@pytest.mark.anyio
async def test_patched_connect_no_match_raises(tmp_path: object) -> None:
    from cassetter.intercept._websockets import WebSocketInterceptor

    path = os.path.join(str(tmp_path), "ws_empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    interceptor = WebSocketInterceptor()
    interceptor.install()
    token = current_cassette.set(cassette)
    try:
        import websockets.asyncio.client

        with pytest.raises(NoMatchError):
            async with websockets.asyncio.client.connect("wss://ws.example.com/unknown"):
                pass
    finally:
        current_cassette.reset(token)
        interceptor.uninstall()


def test_websocket_interceptor_install_uninstall() -> None:
    import websockets.asyncio.client

    from cassetter.intercept._websockets import WebSocketInterceptor

    original = websockets.asyncio.client.connect

    interceptor = WebSocketInterceptor()

    interceptor.install()
    assert websockets.asyncio.client.connect is not original

    interceptor.uninstall()
    assert websockets.asyncio.client.connect is original


# --- gRPC recording ---


@pytest.mark.anyio
async def test_unary_unary_record(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryUnaryCallable

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
        fake_call,  # type: ignore[arg-type]
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
async def test_unary_stream_record(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRUnaryStreamCallable, decode_chunks

    path = os.path.join(str(tmp_path), "grpc_rec_stream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeChunk:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def SerializeToString(self) -> bytes:
            return self._data

    async def fake_stream(*args: object, **kwargs: object) -> AsyncIterator[FakeChunk]:
        yield FakeChunk(b"\x0a")  # type: ignore[misc]
        yield FakeChunk(b"\x0b")  # type: ignore[misc]

    callable_ = VCRUnaryStreamCallable(
        "/pkg.Svc/Stream",
        fake_stream,  # type: ignore[arg-type]
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
async def test_stream_unary_record(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamUnaryCallable

    path = os.path.join(str(tmp_path), "grpc_rec_cstream.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeResponse:
        def SerializeToString(self) -> bytes:
            return b"\xff"

    async def fake_call(request_iter: object, **kwargs: object) -> FakeResponse:
        return FakeResponse()

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # type: ignore[misc]
        yield b"\x02"  # type: ignore[misc]

    callable_ = VCRStreamUnaryCallable(
        "/pkg.Svc/ClientStream",
        fake_call,  # type: ignore[arg-type]
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
async def test_stream_stream_record(tmp_path: object) -> None:
    from cassetter.intercept._grpc import VCRStreamStreamCallable, decode_chunks

    path = os.path.join(str(tmp_path), "grpc_rec_bidi.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    class FakeChunk:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def SerializeToString(self) -> bytes:
            return self._data

    async def fake_bidi(request_iter: object, **kwargs: object) -> AsyncIterator[FakeChunk]:
        yield FakeChunk(b"\x0a")  # type: ignore[misc]
        yield FakeChunk(b"\x0b")  # type: ignore[misc]

    async def request_iter() -> AsyncIterator[bytes]:
        yield b"\x01"  # type: ignore[misc]

    callable_ = VCRStreamStreamCallable(
        "/pkg.Svc/Bidi",
        fake_bidi,  # type: ignore[arg-type]
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
    from cassetter.intercept._grpc import (
        VCRChannel,
        VCRStreamStreamCallable,
        VCRStreamUnaryCallable,
        VCRUnaryStreamCallable,
        VCRUnaryUnaryCallable,
    )

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

    channel = VCRChannel(FakeChannel())  # type: ignore[arg-type]
    assert isinstance(channel.unary_unary("/m"), VCRUnaryUnaryCallable)
    assert isinstance(channel.unary_stream("/m"), VCRUnaryStreamCallable)
    assert isinstance(channel.stream_unary("/m"), VCRStreamUnaryCallable)
    assert isinstance(channel.stream_stream("/m"), VCRStreamStreamCallable)
    assert channel.other_method() == "other"  # __getattr__ delegation


@pytest.mark.anyio
async def test_vcr_channel_close() -> None:
    from cassetter.intercept._grpc import VCRChannel

    class FakeChannel:
        closed = False

        async def close(self) -> None:
            self.closed = True

    fake = FakeChannel()
    channel = VCRChannel(fake)  # type: ignore[arg-type]
    await channel.close()
    assert fake.closed


@pytest.mark.anyio
async def test_vcr_channel_context_manager() -> None:
    from cassetter.intercept._grpc import VCRChannel

    class FakeChannel:
        entered = False
        exited = False

        async def __aenter__(self) -> FakeChannel:
            self.entered = True
            return self

        async def __aexit__(self, *args: object) -> None:
            self.exited = True

        async def close(self) -> None:
            pass

    fake = FakeChannel()
    channel = VCRChannel(fake)  # type: ignore[arg-type]

    async with channel as ch:
        assert ch is channel
    assert fake.entered
    assert fake.exited


# --- gRPC interceptor patching ---


def test_patched_channels_create_vcr_channels() -> None:
    from cassetter.intercept._grpc import GrpcInterceptor

    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    cassette.load()

    interceptor = GrpcInterceptor()
    interceptor.install()
    try:
        # Verify the patched function returns VCRChannel
        import grpc.aio

        patched_fn = grpc.aio.insecure_channel
        assert patched_fn is not interceptor._original_insecure
    finally:
        interceptor.uninstall()


# --- gRPC async helpers ---


@pytest.mark.anyio
async def test_grpcasync_iter() -> None:
    from cassetter.intercept._grpc import async_iter

    results = [item async for item in async_iter([b"\x01", b"\x02"])]
    assert results == [b"\x01", b"\x02"]


def test_grpciter_bytes() -> None:
    from cassetter.intercept._grpc import iter_bytes

    result = iter_bytes([b"\x01"], lambda b: b)
    assert result is not None
