from __future__ import annotations

from cassetter._core import (
    Body,
    GrpcInteraction,
    GrpcRequest,
    GrpcResponse,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    SecurityConfig,
    WsFrame,
    WsInteraction,
    scrub_grpc_interaction,
    scrub_interaction,
    scrub_ws_interaction,
)


def test_security_default_filter_headers() -> None:
    config = SecurityConfig()
    assert "authorization" in config.filter_headers
    assert "cookie" in config.filter_headers
    assert "x-api-key" in config.filter_headers


def test_security_default_filter_query_parameters() -> None:
    config = SecurityConfig()
    assert "api_key" in config.filter_query_parameters
    assert "access_token" in config.filter_query_parameters


def test_security_default_body_scrub_patterns() -> None:
    config = SecurityConfig()
    assert "password" in config.body_scrub_patterns
    assert "access_token" in config.body_scrub_patterns


def test_scrub_headers() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1",
            {"authorization": ["Bearer secret"], "content-type": ["application/json"]},
        ),
        response=HttpResponse(
            200,
            {"set-cookie": ["session=abc"], "content-type": ["application/json"]},
            Body("json", {"result": "ok"}),
        ),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert "authorization" not in scrubbed.request.headers
    assert "content-type" in scrubbed.request.headers
    assert "set-cookie" not in scrubbed.response.headers


def test_scrub_ws_headers() -> None:
    interaction = WsInteraction(
        "wss://api.example.com/v1",
        {"authorization": ["Bearer secret"], "content-type": ["application/json"]},
    )
    config = SecurityConfig()
    scrubbed = scrub_ws_interaction(interaction, config)

    assert "authorization" not in scrubbed.headers
    assert "content-type" in scrubbed.headers


def test_scrub_ws_frame_bodies() -> None:
    frames = [
        WsFrame("send", "text", Body("json", {"access_token": "tok_abc", "channel": "ticker"}), 0),
        WsFrame("recv", "text", Body("text", '{"password": "secret", "ok": true}'), 10),
        WsFrame("recv", "binary", Body("binary", b"\x01\x02"), 20),
    ]
    interaction = WsInteraction("wss://api.example.com/v1", {}, frames)
    config = SecurityConfig()
    scrubbed = scrub_ws_interaction(interaction, config)

    assert scrubbed.frames[0].body.content["access_token"] == "[FILTERED]"
    assert scrubbed.frames[0].body.content["channel"] == "ticker"
    assert '"password": "[FILTERED]"' in scrubbed.frames[1].body.content
    assert '"ok": true' in scrubbed.frames[1].body.content
    assert scrubbed.frames[2].body.content == b"\x01\x02"


def test_scrub_grpc_metadata() -> None:
    interaction = GrpcInteraction(
        request=GrpcRequest(
            "/pkg.Svc/M",
            {"authorization": ["Bearer secret"], "x-request-id": ["abc"]},
            Body("binary", b"\x0a\x0b"),
        ),
        response=GrpcResponse(0, "OK", {"set-cookie": ["session=abc"]}, Body("binary", b"\x12\x03")),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_grpc_interaction(interaction, config)

    assert "authorization" not in scrubbed.request.metadata
    assert scrubbed.request.metadata["x-request-id"] == ["abc"]
    assert "set-cookie" not in scrubbed.response.metadata
    assert scrubbed.request.body.content == b"\x0a\x0b"


def test_scrub_grpc_json_debug() -> None:
    interaction = GrpcInteraction(
        request=GrpcRequest("/pkg.Svc/M", {}, Body("binary", b"\x0a")),
        response=GrpcResponse(0, "OK", {}, Body("binary", b"\x12")),
        recorded_at="2026-01-01T00:00:00Z",
        json_debug={
            "request": {"password": "hunter2", "user": "alice"},
            "response": {"access_token": "tok_abc"},
        },
    )
    config = SecurityConfig()
    scrubbed = scrub_grpc_interaction(interaction, config)

    assert scrubbed.json_debug["request"]["password"] == "[FILTERED]"
    assert scrubbed.json_debug["request"]["user"] == "alice"
    assert scrubbed.json_debug["response"]["access_token"] == "[FILTERED]"


def test_scrub_grpc_no_json_debug() -> None:
    interaction = GrpcInteraction(
        request=GrpcRequest("/pkg.Svc/M", {}, Body("binary", b"\x0a")),
        response=GrpcResponse(0, "OK", {}, Body("binary", b"\x12")),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_grpc_interaction(interaction, config)

    assert scrubbed.json_debug is None


def test_scrub_ws_headers_custom_filter() -> None:
    interaction = WsInteraction("wss://api.example.com/v1", {"x-trace-id": ["abc"]})
    config = SecurityConfig(filter_headers=["x-trace-id"])
    scrubbed = scrub_ws_interaction(interaction, config)

    assert "x-trace-id" not in scrubbed.headers


def test_scrub_query_params() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1?api_key=secret&format=json",
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert "secret" not in scrubbed.request.uri
    assert "FILTERED" in scrubbed.request.uri
    assert "format=json" in scrubbed.request.uri


def test_scrub_query_params_preserves_encoding() -> None:
    """Query params with special chars like commas must keep their original encoding."""
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://httpbin.org/get?product=123,456&api_key=secret",
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert "product=123,456" in scrubbed.request.uri
    assert "api_key=[FILTERED]" in scrubbed.request.uri


def test_scrub_json_body() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/auth",
            body=Body("json", {"username": "alice", "password": "secret123"}),
        ),
        response=HttpResponse(
            200,
            body=Body("json", {"access_token": "tok_abc", "expires_in": 3600}),
        ),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert scrubbed.request.body.content["password"] == "[FILTERED]"
    assert scrubbed.request.body.content["username"] == "alice"
    assert scrubbed.response.body.content["access_token"] == "[FILTERED]"
    assert scrubbed.response.body.content["expires_in"] == 3600


def test_scrub_custom_replacement() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/auth",
            body=Body("json", {"password": "secret"}),
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig(replacement="***REDACTED***")
    scrubbed = scrub_interaction(interaction, config)

    assert scrubbed.request.body.content["password"] == "***REDACTED***"


def test_scrub_custom_filter_list() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1",
            {"x-custom-secret": ["my-secret"], "content-type": ["text/plain"]},
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig(
        filter_headers=["x-custom-secret"],
        filter_query_parameters=[],
        body_scrub_patterns=[],
    )
    scrubbed = scrub_interaction(interaction, config)

    assert "x-custom-secret" not in scrubbed.request.headers
    assert "content-type" in scrubbed.request.headers
