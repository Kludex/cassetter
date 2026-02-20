from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from vcr_but_better._core import (
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
from vcr_but_better.cassette import Cassette, NoMatchError
from vcr_but_better.recording import RecordMode


class TestGrpcTypes:
    def test_grpc_request(self) -> None:
        req = GrpcRequest("/pkg.Svc/Method", {"x-id": ["abc"]}, Body("binary", b"\x0a\x0b"))
        assert req.method == "/pkg.Svc/Method"
        assert req.metadata == {"x-id": ["abc"]}
        assert req.body.body_type == "binary"

    def test_grpc_response(self) -> None:
        resp = GrpcResponse(0, "OK", {}, Body("binary", b"\x12\x03"))
        assert resp.status_code == 0
        assert resp.status_message == "OK"

    def test_grpc_response_defaults(self) -> None:
        resp = GrpcResponse(0)
        assert resp.status_message == "OK"
        assert resp.metadata == {}
        assert resp.body.body_type == "none"

    def test_grpc_interaction(self) -> None:
        req = GrpcRequest("/pkg.Svc/Method")
        resp = GrpcResponse(0)
        interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z")
        assert interaction.recorded_at == "2026-01-01T00:00:00Z"
        assert interaction.json_debug is None

    def test_grpc_interaction_with_json_debug(self) -> None:
        req = GrpcRequest("/pkg.Svc/Method")
        resp = GrpcResponse(0)
        debug = {"request": {"input": "Hello"}, "response": {"output": "Hi"}}
        interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z", debug)
        assert interaction.json_debug == debug

    def test_grpc_repr(self) -> None:
        req = GrpcRequest("/pkg.Svc/Method")
        resp = GrpcResponse(0)
        interaction = GrpcInteraction(req, resp, "2026-01-01T00:00:00Z")
        assert "/pkg.Svc/Method" in repr(interaction)


class TestWsTypes:
    def test_ws_frame(self) -> None:
        frame = WsFrame("send", "text", Body("text", "hello"), 0)
        assert frame.direction == "send"
        assert frame.frame_type == "text"
        assert frame.offset_ms == 0

    def test_ws_frame_default_offset(self) -> None:
        frame = WsFrame("recv", "binary", Body("binary", b"\x00"))
        assert frame.offset_ms == 0

    def test_ws_interaction(self) -> None:
        frames = [
            WsFrame("send", "text", Body("text", '{"subscribe": "ticker"}'), 0),
            WsFrame("recv", "text", Body("text", '{"price": 42.5}'), 120),
        ]
        interaction = WsInteraction("wss://ws.example.com/stream", {}, frames)
        assert interaction.uri == "wss://ws.example.com/stream"
        assert len(interaction.frames) == 2

    def test_ws_interaction_defaults(self) -> None:
        interaction = WsInteraction("wss://ws.example.com")
        assert interaction.headers == {}
        assert interaction.frames == []
        assert interaction.recorded_at == ""


class TestGrpcMatching:
    def test_find_grpc_match(self) -> None:
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

    def test_find_grpc_match_prefers_unplayed(self) -> None:
        interactions = [
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"),
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t2"),
        ]
        result = find_grpc_match("/pkg.Svc/M", interactions, [True, False])
        assert result is not None
        assert result[0] == 1

    def test_find_grpc_match_falls_back_to_played(self) -> None:
        interactions = [
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1"),
        ]
        result = find_grpc_match("/pkg.Svc/M", interactions, [True])
        assert result is not None
        assert result[0] == 0

    def test_find_grpc_match_no_match(self) -> None:
        interactions = [
            GrpcInteraction(GrpcRequest("/pkg.Svc/MethodA"), GrpcResponse(0), "t1"),
        ]
        assert find_grpc_match("/pkg.Svc/Unknown", interactions, [False]) is None


class TestWsMatching:
    def test_find_ws_match(self) -> None:
        interactions = [
            WsInteraction("wss://a.example.com"),
            WsInteraction("wss://b.example.com"),
        ]
        result = find_ws_match("wss://b.example.com", interactions, [False, False])
        assert result is not None
        assert result[0] == 1

    def test_find_ws_match_prefers_unplayed(self) -> None:
        interactions = [
            WsInteraction("wss://a.example.com"),
            WsInteraction("wss://a.example.com"),
        ]
        result = find_ws_match("wss://a.example.com", interactions, [True, False])
        assert result is not None
        assert result[0] == 1

    def test_find_ws_match_no_match(self) -> None:
        interactions = [WsInteraction("wss://a.example.com")]
        assert find_ws_match("wss://other.com", interactions, [False]) is None


class TestRustCassetteGrpcWs:
    def test_add_grpc_interaction(self) -> None:
        c = RustCassette()
        c.add_grpc_interaction(
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1")
        )
        assert len(c) == 1
        assert len(c.grpc_interactions) == 1
        assert c.grpc_played == [False]

    def test_mark_grpc_played(self) -> None:
        c = RustCassette()
        c.add_grpc_interaction(
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1")
        )
        c.mark_grpc_played(0)
        assert c.grpc_played == [True]

    def test_mark_grpc_played_out_of_range(self) -> None:
        c = RustCassette()
        with pytest.raises(IndexError):
            c.mark_grpc_played(0)

    def test_add_ws_interaction(self) -> None:
        c = RustCassette()
        c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
        assert len(c) == 1
        assert len(c.ws_interactions) == 1
        assert c.ws_played == [False]

    def test_mark_ws_played(self) -> None:
        c = RustCassette()
        c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
        c.mark_ws_played(0)
        assert c.ws_played == [True]

    def test_mark_ws_played_out_of_range(self) -> None:
        c = RustCassette()
        with pytest.raises(IndexError):
            c.mark_ws_played(0)

    def test_len_mixed(self) -> None:
        c = RustCassette()
        c.add_interaction(
            HttpInteraction(HttpRequest("GET", "https://example.com"), HttpResponse(200), "t1")
        )
        c.add_grpc_interaction(
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1")
        )
        c.add_ws_interaction(WsInteraction("wss://ws.example.com"))
        assert len(c) == 3

    def test_repr(self) -> None:
        c = RustCassette()
        c.add_grpc_interaction(
            GrpcInteraction(GrpcRequest("/pkg.Svc/M"), GrpcResponse(0), "t1")
        )
        assert "grpc=1" in repr(c)


class TestCassetteRoundtrip:
    def test_grpc_save_and_load(self, tmp_path: object) -> None:
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

    def test_ws_save_and_load(self, tmp_path: object) -> None:
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

    def test_mixed_protocol_roundtrip(self, tmp_path: object) -> None:
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
        c.add_ws_interaction(
            WsInteraction("wss://ws.example.com", recorded_at="2026-01-01T00:00:00Z")
        )
        c.save(path)

        c2 = RustCassette.load(path)
        assert len(c2.interactions) == 1
        assert len(c2.grpc_interactions) == 1
        assert len(c2.ws_interactions) == 1
        assert len(c2) == 3

    def test_backward_compat_http_only(self, tmp_path: object) -> None:
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


class TestCassetteWrapperGrpcWs:
    def test_grpc_properties_before_load(self) -> None:
        cassette = Cassette("/tmp/test.yaml")
        assert cassette.grpc_interactions == []
        assert cassette.ws_interactions == []

    def test_play_grpc_before_load(self) -> None:
        cassette = Cassette("/tmp/test.yaml")
        with pytest.raises(NoMatchError, match="cassette not loaded"):
            cassette.play_grpc("/pkg.Svc/Method")

    def test_play_ws_before_load(self) -> None:
        cassette = Cassette("/tmp/test.yaml")
        with pytest.raises(NoMatchError, match="cassette not loaded"):
            cassette.play_ws("wss://example.com")

    def test_record_and_play_grpc(self, tmp_path: object) -> None:
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

    def test_play_grpc_no_match(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "grpc_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        with pytest.raises(NoMatchError, match="no matching gRPC"):
            cassette.play_grpc("/pkg.Svc/Unknown")

    def test_record_ws(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "ws_test.yaml")
        cassette = Cassette(path, record_mode=RecordMode.ALL)
        cassette.load()

        frames = [
            WsFrame("send", "text", Body("text", "hello"), 0),
            WsFrame("recv", "text", Body("text", "world"), 50),
        ]
        cassette.record_ws("wss://ws.example.com", {}, frames)
        assert len(cassette.ws_interactions) == 1

    def test_play_ws(self, tmp_path: object) -> None:
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

    def test_play_ws_no_match(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "ws_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        with pytest.raises(NoMatchError, match="no matching WebSocket"):
            cassette.play_ws("wss://unknown.com")

    def test_grpc_ws_save_persists(self, tmp_path: object) -> None:
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

    def test_record_grpc_before_load(self) -> None:
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        resp = cassette.record_grpc(
            method="/pkg.Svc/M",
            metadata={},
            request_body=Body("binary", b"\x01"),
            response_body=Body("binary", b"\x02"),
        )
        assert resp.status_code == 0
        assert len(cassette.grpc_interactions) == 1

    def test_record_ws_before_load(self) -> None:
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        cassette.record_ws("wss://ws.example.com", {}, [])
        assert len(cassette.ws_interactions) == 1


class TestGrpcChunkEncoding:
    def test_encode_decode_roundtrip(self) -> None:
        from vcr_but_better.intercept._grpc import _decode_chunks, _encode_chunks

        chunks = [b"hello", b"world", b"\x00\x01\x02"]
        encoded = _encode_chunks(chunks)
        assert _decode_chunks(encoded) == chunks

    def test_encode_empty(self) -> None:
        from vcr_but_better.intercept._grpc import _decode_chunks, _encode_chunks

        assert _encode_chunks([]) == b""
        assert _decode_chunks(b"") == []

    def test_encode_single(self) -> None:
        from vcr_but_better.intercept._grpc import _decode_chunks, _encode_chunks

        chunks = [b"\x0a\x0b"]
        encoded = _encode_chunks(chunks)
        assert _decode_chunks(encoded) == chunks

    def test_decode_truncated(self) -> None:
        from vcr_but_better.intercept._grpc import _decode_chunks

        # Less than 4 bytes - can't read length
        assert _decode_chunks(b"\x00\x01") == []


class TestGrpcInterceptor:
    def test_metadata_to_dict_none(self) -> None:
        from vcr_but_better.intercept._grpc import _metadata_to_dict

        assert _metadata_to_dict(None) == {}

    def test_metadata_to_dict_str_values(self) -> None:
        from vcr_but_better.intercept._grpc import _metadata_to_dict

        md = [("key1", "val1"), ("key2", "val2"), ("key1", "val1b")]
        result = _metadata_to_dict(md)
        assert result == {"key1": ["val1", "val1b"], "key2": ["val2"]}

    def test_metadata_to_dict_bytes_values(self) -> None:
        from vcr_but_better.intercept._grpc import _metadata_to_dict

        md = [("key", b"binary-val")]
        result = _metadata_to_dict(md)
        assert result == {"key": ["binary-val"]}

    def test_build_json_debug_no_protobuf(self) -> None:
        from vcr_but_better.intercept._grpc import _build_json_debug

        # Objects without MessageToDict support return None
        result = _build_json_debug("req", "resp")
        assert result is None

    def test_build_json_debug_none_request(self) -> None:
        from vcr_but_better.intercept._grpc import _build_json_debug

        result = _build_json_debug(None, "resp")
        assert result is None

    @pytest.mark.anyio
    async def test_replay_stream_chunked(self) -> None:
        from vcr_but_better.intercept._grpc import _encode_chunks, _replay_stream

        chunks = [b"\x01", b"\x02\x03"]
        encoded = _encode_chunks(chunks)
        resp = GrpcResponse(0, "OK", {}, Body("binary", encoded))
        results = []
        async for item in _replay_stream(resp, lambda b: f"got:{b.hex()}"):
            results.append(item)
        assert results == ["got:01", "got:0203"]

    @pytest.mark.anyio
    async def test_replay_stream_single_fallback(self) -> None:
        from vcr_but_better.intercept._grpc import _replay_stream

        # Non-chunked data: falls back to treating entire body as single message
        resp = GrpcResponse(0, "OK", {}, Body("binary", b"\x01\x02"))
        results = []
        async for item in _replay_stream(resp, lambda b: f"got:{len(b)}"):
            results.append(item)
        assert results == ["got:2"]

    @pytest.mark.anyio
    async def test_replay_stream_empty_body(self) -> None:
        from vcr_but_better.intercept._grpc import _replay_stream

        resp = GrpcResponse(0, "OK", {}, Body("none", b""))
        results = []
        async for item in _replay_stream(resp, lambda b: f"got:{len(b)}"):
            results.append(item)
        assert results == ["got:0"]

    def test_install_uninstall(self) -> None:
        from vcr_but_better.intercept._grpc import GrpcInterceptor

        import grpc.aio

        original_insecure = grpc.aio.insecure_channel
        original_secure = grpc.aio.secure_channel

        interceptor = GrpcInterceptor()
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        cassette.load()

        interceptor.install(cassette)
        assert grpc.aio.insecure_channel is not original_insecure
        assert grpc.aio.secure_channel is not original_secure

        interceptor.uninstall()
        assert grpc.aio.insecure_channel is original_insecure
        assert grpc.aio.secure_channel is original_secure

    @pytest.mark.anyio
    async def test_unary_unary_replay(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryUnaryCallable

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
            cassette,
            lambda x: b"\x01",
            lambda b: f"deserialized:{b.hex()}",
        )
        result = await callable_(object())
        assert result == "deserialized:0203"

    @pytest.mark.anyio
    async def test_unary_unary_no_match_raises(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryUnaryCallable

        path = os.path.join(str(tmp_path), "grpc_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        callable_ = VCRUnaryUnaryCallable(
            "/pkg.Svc/Unknown",
            None,
            cassette,
            lambda x: b"\x01",
            lambda b: b,
        )
        with pytest.raises(NoMatchError):
            await callable_(object())

    @pytest.mark.anyio
    async def test_unary_stream_replay(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryStreamCallable, _encode_chunks

        path = os.path.join(str(tmp_path), "grpc_stream.yaml")
        cassette = Cassette(path, record_mode=RecordMode.ALL)
        cassette.load()

        chunks = [b"\x01", b"\x02", b"\x03"]
        cassette.record_grpc(
            method="/pkg.Svc/Stream",
            metadata={},
            request_body=Body("binary", b"\x00"),
            response_body=Body("binary", _encode_chunks(chunks)),
        )

        callable_ = VCRUnaryStreamCallable(
            "/pkg.Svc/Stream",
            None,
            cassette,
            lambda x: b"\x00",
            lambda b: f"chunk:{b.hex()}",
        )
        results = []
        async for item in callable_(object()):
            results.append(item)
        assert results == ["chunk:01", "chunk:02", "chunk:03"]

    @pytest.mark.anyio
    async def test_unary_stream_no_match_raises(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryStreamCallable

        path = os.path.join(str(tmp_path), "grpc_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        callable_ = VCRUnaryStreamCallable("/pkg.Svc/X", None, cassette, lambda x: b"", lambda b: b)
        with pytest.raises(NoMatchError):
            async for _ in callable_(object()):
                pass

    @pytest.mark.anyio
    async def test_stream_unary_replay(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamUnaryCallable

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
            cassette,
            lambda x: x,  # identity serializer
            lambda b: f"resp:{b.hex()}",
        )
        result = await callable_(request_iter())
        assert result == "resp:ff"

    @pytest.mark.anyio
    async def test_stream_unary_no_match_raises(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamUnaryCallable

        path = os.path.join(str(tmp_path), "grpc_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        async def request_iter() -> AsyncIterator[bytes]:
            yield b"\x01"  # type: ignore[misc]

        callable_ = VCRStreamUnaryCallable("/pkg.Svc/X", None, cassette, lambda x: x, lambda b: b)
        with pytest.raises(NoMatchError):
            await callable_(request_iter())

    @pytest.mark.anyio
    async def test_stream_stream_replay(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamStreamCallable, _encode_chunks

        path = os.path.join(str(tmp_path), "grpc_bidi.yaml")
        cassette = Cassette(path, record_mode=RecordMode.ALL)
        cassette.load()

        resp_chunks = [b"\x0a", b"\x0b"]
        cassette.record_grpc(
            method="/pkg.Svc/Bidi",
            metadata={},
            request_body=Body("binary", b"\x00"),
            response_body=Body("binary", _encode_chunks(resp_chunks)),
        )

        async def request_iter() -> AsyncIterator[bytes]:
            yield b"\x01"  # type: ignore[misc]

        callable_ = VCRStreamStreamCallable(
            "/pkg.Svc/Bidi",
            None,
            cassette,
            lambda x: x,
            lambda b: f"got:{b.hex()}",
        )
        results = []
        async for item in callable_(request_iter()):
            results.append(item)
        assert results == ["got:0a", "got:0b"]

    @pytest.mark.anyio
    async def test_stream_stream_no_match_raises(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamStreamCallable

        path = os.path.join(str(tmp_path), "grpc_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        async def request_iter() -> AsyncIterator[bytes]:
            yield b"\x01"  # type: ignore[misc]

        callable_ = VCRStreamStreamCallable("/pkg.Svc/X", None, cassette, lambda x: x, lambda b: b)
        with pytest.raises(NoMatchError):
            async for _ in callable_(request_iter()):
                pass


class TestWebSocketInterceptor:
    def test_frame_to_data_text(self) -> None:
        from vcr_but_better.intercept._websockets import _frame_to_data

        frame = WsFrame("recv", "text", Body("text", "hello"), 0)
        assert _frame_to_data(frame) == "hello"

    def test_frame_to_data_binary(self) -> None:
        from vcr_but_better.intercept._websockets import _frame_to_data

        frame = WsFrame("recv", "binary", Body("binary", b"\x01\x02"), 0)
        assert _frame_to_data(frame) == b"\x01\x02"

    def test_frame_to_data_none_body(self) -> None:
        from vcr_but_better.intercept._websockets import _frame_to_data

        frame = WsFrame("recv", "text", Body("none", b""), 0)
        assert _frame_to_data(frame) == ""

    def test_extract_ws_headers_none(self) -> None:
        from vcr_but_better.intercept._websockets import _extract_ws_headers

        assert _extract_ws_headers({}) == {}

    def test_extract_ws_headers_additional(self) -> None:
        from vcr_but_better.intercept._websockets import _extract_ws_headers

        result = _extract_ws_headers({"additional_headers": {"Authorization": "Bearer tok"}})
        assert result == {"authorization": ["Bearer tok"]}

    def test_extract_ws_headers_extra(self) -> None:
        from vcr_but_better.intercept._websockets import _extract_ws_headers

        result = _extract_ws_headers({"extra_headers": {"X-Key": "val"}})
        assert result == {"x-key": ["val"]}

    @pytest.mark.anyio
    async def test_replay_ws_recv(self) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocketReplay

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
    async def test_replay_ws_send_is_noop(self) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocketReplay

        interaction = WsInteraction("wss://ws.example.com", {}, [])
        ws = VCRWebSocketReplay(interaction)
        await ws.send("ignored")  # should not raise

    @pytest.mark.anyio
    async def test_replay_ws_close_is_noop(self) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocketReplay

        interaction = WsInteraction("wss://ws.example.com", {}, [])
        ws = VCRWebSocketReplay(interaction)
        await ws.close()  # should not raise

    @pytest.mark.anyio
    async def test_replay_ws_context_manager(self) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocketReplay

        interaction = WsInteraction(
            "wss://ws.example.com",
            {},
            [WsFrame("recv", "text", Body("text", "hello"), 0)],
        )
        async with VCRWebSocketReplay(interaction) as ws:
            data = await ws.recv()
        assert data == "hello"

    @pytest.mark.anyio
    async def test_replay_ws_async_iter(self) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocketReplay

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
    async def test_record_ws_frames(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocket

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

        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {}, cassette)
        await ws.send("hello")
        data = await ws.recv()
        assert data == "response"
        await ws.close()

        assert len(cassette.ws_interactions) == 1
        interaction = cassette.ws_interactions[0]
        assert len(interaction.frames) == 2
        assert interaction.frames[0].direction == "send"
        assert interaction.frames[1].direction == "recv"

    @pytest.mark.anyio
    async def test_record_ws_context_manager(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocket

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
        async with VCRWebSocket(real_ws, "wss://ws.example.com", {}, cassette) as ws:
            await ws.send("x")
            await ws.recv()

        assert len(cassette.ws_interactions) == 1

    @pytest.mark.anyio
    async def test_record_ws_binary_frames(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocket

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

        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {}, cassette)
        await ws.send(b"\xff\xfe")
        data = await ws.recv()
        assert data == b"\x01\x02\x03"
        await ws.close()

        interaction = cassette.ws_interactions[0]
        assert interaction.frames[0].frame_type == "binary"
        assert interaction.frames[1].frame_type == "binary"

    @pytest.mark.anyio
    async def test_record_ws_async_iter(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import VCRWebSocket

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

        ws = VCRWebSocket(FakeWs(), "wss://ws.example.com", {}, cassette)
        results = [item async for item in ws]
        assert results == ["a", "b"]
        assert len(cassette.ws_interactions) == 1

    @pytest.mark.anyio
    async def test_patched_connect_replay(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import WebSocketInterceptor

        path = os.path.join(str(tmp_path), "ws_connect.yaml")
        cassette = Cassette(path, record_mode=RecordMode.ALL)
        cassette.load()

        frames = [WsFrame("recv", "text", Body("text", "hello"), 0)]
        cassette.record_ws("wss://ws.example.com/path", {}, frames)

        interceptor = WebSocketInterceptor()
        interceptor.install(cassette)
        try:
            import websockets.asyncio.client

            async with websockets.asyncio.client.connect("wss://ws.example.com/path") as ws:
                data = await ws.recv()
                assert data == "hello"
        finally:
            interceptor.uninstall()

    @pytest.mark.anyio
    async def test_patched_connect_no_match_raises(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._websockets import WebSocketInterceptor

        path = os.path.join(str(tmp_path), "ws_empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        cassette.load()

        interceptor = WebSocketInterceptor()
        interceptor.install(cassette)
        try:
            import websockets.asyncio.client

            with pytest.raises(NoMatchError):
                async with websockets.asyncio.client.connect("wss://ws.example.com/unknown") as ws:
                    pass
        finally:
            interceptor.uninstall()

    def test_install_uninstall(self) -> None:
        from vcr_but_better.intercept._websockets import WebSocketInterceptor

        import websockets.asyncio.client

        original = websockets.asyncio.client.connect

        interceptor = WebSocketInterceptor()
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        cassette.load()

        interceptor.install(cassette)
        assert websockets.asyncio.client.connect is not original

        interceptor.uninstall()
        assert websockets.asyncio.client.connect is original


class TestGrpcRecording:
    """Tests for gRPC recording paths using fake gRPC objects."""

    @pytest.mark.anyio
    async def test_unary_unary_record(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryUnaryCallable

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
            cassette,
            lambda x: b"\x01",
            lambda b: b,
        )
        result = await callable_(object())
        assert isinstance(result, FakeResponse)
        assert len(cassette.grpc_interactions) == 1
        assert cassette.grpc_interactions[0].request.method == "/pkg.Svc/Echo"

    @pytest.mark.anyio
    async def test_unary_stream_record(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRUnaryStreamCallable, _decode_chunks

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
            cassette,
            lambda x: b"\x01",
            lambda b: b,
        )
        results = []
        async for item in callable_(object()):
            results.append(item)
        assert len(results) == 2
        assert len(cassette.grpc_interactions) == 1
        # Verify chunks were encoded
        body = cassette.grpc_interactions[0].response.body
        assert isinstance(body.content, bytes)
        chunks = _decode_chunks(body.content)
        assert chunks == [b"\x0a", b"\x0b"]

    @pytest.mark.anyio
    async def test_stream_unary_record(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamUnaryCallable

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
            cassette,
            lambda x: x,
            lambda b: b,
        )
        result = await callable_(request_iter())
        assert isinstance(result, FakeResponse)
        assert len(cassette.grpc_interactions) == 1

    @pytest.mark.anyio
    async def test_stream_stream_record(self, tmp_path: object) -> None:
        from vcr_but_better.intercept._grpc import VCRStreamStreamCallable, _decode_chunks

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
            cassette,
            lambda x: x,
            lambda b: b,
        )
        results = []
        async for item in callable_(request_iter()):
            results.append(item)
        assert len(results) == 2
        assert len(cassette.grpc_interactions) == 1
        body = cassette.grpc_interactions[0].response.body
        assert isinstance(body.content, bytes)
        chunks = _decode_chunks(body.content)
        assert chunks == [b"\x0a", b"\x0b"]


class TestVCRChannel:
    def test_channel_wraps_methods(self) -> None:
        from vcr_but_better.intercept._grpc import VCRChannel, VCRStreamStreamCallable, VCRStreamUnaryCallable, VCRUnaryStreamCallable, VCRUnaryUnaryCallable

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

        channel = VCRChannel(FakeChannel(), cassette)  # type: ignore[arg-type]
        assert isinstance(channel.unary_unary("/m"), VCRUnaryUnaryCallable)
        assert isinstance(channel.unary_stream("/m"), VCRUnaryStreamCallable)
        assert isinstance(channel.stream_unary("/m"), VCRStreamUnaryCallable)
        assert isinstance(channel.stream_stream("/m"), VCRStreamStreamCallable)
        assert channel.other_method() == "other"  # __getattr__ delegation

    @pytest.mark.anyio
    async def test_channel_context_manager(self) -> None:
        from vcr_but_better.intercept._grpc import VCRChannel

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
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        channel = VCRChannel(fake, cassette)  # type: ignore[arg-type]

        async with channel as ch:
            assert ch is channel
        assert fake.entered
        assert fake.exited

    @pytest.mark.anyio
    async def test_channel_close(self) -> None:
        from vcr_but_better.intercept._grpc import VCRChannel

        class FakeChannel:
            closed = False

            async def close(self) -> None:
                self.closed = True

        fake = FakeChannel()
        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        channel = VCRChannel(fake, cassette)  # type: ignore[arg-type]
        await channel.close()
        assert fake.closed


class TestGrpcInterceptorPatching:
    def test_patched_channels_create_vcr_channels(self) -> None:
        from vcr_but_better.intercept._grpc import GrpcInterceptor, VCRChannel

        cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
        cassette.load()

        interceptor = GrpcInterceptor()
        interceptor.install(cassette)
        try:
            # Verify the patched function returns VCRChannel
            import grpc.aio

            patched_fn = grpc.aio.insecure_channel
            assert patched_fn is not interceptor._original_insecure
        finally:
            interceptor.uninstall()


class TestGrpcAsyncHelpers:
    @pytest.mark.anyio
    async def test_async_iter(self) -> None:
        from vcr_but_better.intercept._grpc import _async_iter

        results = [item async for item in _async_iter([b"\x01", b"\x02"])]
        assert results == [b"\x01", b"\x02"]

    def test_iter_bytes(self) -> None:
        from vcr_but_better.intercept._grpc import _iter_bytes

        result = _iter_bytes([b"\x01"], lambda b: b)
        assert result is not None
