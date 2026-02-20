from __future__ import annotations

import os

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
