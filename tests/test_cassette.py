from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from cassetter._core import (
    Body,
    Cassette as RustCassette,
    GrpcInteraction,
    GrpcRequest,
    GrpcResponse,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    SecurityConfig,
    WsInteraction,
    process_body,
    scrub_interaction,
)
from cassetter.cassette import (
    Cassette,
    CassetteExpiredError,
    CassetteExpiredWarning,
    CassetteLoadError,
    NoMatchError,
    _parse_duration,
)
from cassetter.recording import RecordMode


def test_rust_cassette_create_empty() -> None:
    c = RustCassette()
    assert c.version == 1
    assert len(c) == 0
    assert c.unplayed_count == 0


def test_rust_cassette_add_interaction() -> None:
    c = RustCassette()
    interaction = HttpInteraction(
        request=HttpRequest("GET", "https://example.com/"),
        response=HttpResponse(200, body=Body("text", "ok")),
        recorded_at="2026-01-01T00:00:00Z",
    )
    c.add_interaction(interaction)
    assert len(c) == 1
    assert c.unplayed_count == 1


def test_rust_cassette_mark_played() -> None:
    c = RustCassette()
    interaction = HttpInteraction(
        request=HttpRequest("GET", "https://example.com/"),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    c.add_interaction(interaction)
    c.mark_played(0)
    assert c.unplayed_count == 0


def test_rust_cassette_save_and_load(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")

    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest(
                "POST",
                "https://api.example.com/chat",
                {"content-type": ["application/json"]},
                Body("json", {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}),
            ),
            response=HttpResponse(
                200,
                {"content-type": ["application/json"]},
                Body("json", {"id": "chatcmpl-abc", "choices": [{"message": {"content": "Hello!"}}]}),
            ),
            recorded_at="2026-02-20T10:30:01Z",
        )
    )
    c.save(path)

    # Verify the file is readable YAML
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "version: 1" in content
    assert "POST" in content
    assert "gpt-4o" in content

    # Load it back
    c2 = RustCassette.load(path)
    assert len(c2) == 1
    assert c2.interactions[0].request.method == "POST"
    assert c2.interactions[0].response.status == 200


def test_rust_cassette_preserves_json_key_order(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "key-order.yaml")
    raw = b'{"id":"chatcmpl-abc","choices":[],"created":1,"usage":{"total_tokens":3,"prompt_tokens":1}}'

    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("POST", "https://api.example.com/chat", {}, Body("none")),
            response=HttpResponse(
                200,
                {"content-type": ["application/json"]},
                process_body(raw, "application/json"),
            ),
            recorded_at="2026-02-20T10:30:01Z",
        )
    )
    c.save(path)

    with open(path) as f:
        content = f.read()
    assert content.index("id: chatcmpl-abc") < content.index("choices: []")

    replayed = RustCassette.load(path).interactions[0].response.body.content
    assert json.dumps(replayed, separators=(",", ":")).encode() == raw


def test_rust_cassette_load_nonexistent() -> None:
    with pytest.raises(FileNotFoundError):
        RustCassette.load("/nonexistent/path.yaml")


def test_cassette_path() -> None:
    cassette = Cassette("/tmp/test.yaml")
    assert cassette.path == "/tmp/test.yaml"


def test_cassette_record_mode() -> None:
    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    assert cassette.record_mode == RecordMode.ALL


def test_cassette_interactions_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml")
    assert cassette.interactions == []


def test_cassette_can_record() -> None:
    assert Cassette("/tmp/t.yaml", record_mode=RecordMode.ALL).can_record is True
    assert Cassette("/tmp/t.yaml", record_mode=RecordMode.NEW_EPISODES).can_record is True
    assert Cassette("/tmp/t.yaml", record_mode=RecordMode.REWRITE).can_record is True
    assert Cassette("/tmp/t.yaml", record_mode=RecordMode.ONCE).can_record is True
    assert Cassette("/tmp/t.yaml", record_mode=RecordMode.NONE).can_record is False


def test_cassette_play_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml")
    with pytest.raises(NoMatchError, match="cassette not loaded"):
        cassette.play("GET", "https://example.com", {}, None)


def test_cassette_record_before_load() -> None:
    cassette = Cassette("/tmp/test.yaml", record_mode=RecordMode.ALL)
    response = cassette.record(
        method="GET",
        uri="https://example.com/",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"ok",
    )
    assert response.status == 200
    assert len(cassette.interactions) == 1


def test_cassette_load_existing_file(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "existing.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)

    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    assert len(cassette.interactions) == 1


def test_record_mode_none_missing_file() -> None:
    cassette = Cassette("/nonexistent.yaml", record_mode=RecordMode.NONE)
    cassette.load()
    # Missing cassette in NONE mode creates empty cassette - no error
    assert cassette.interactions == []


def test_record_mode_once_creates_new(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "new.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ONCE)
    cassette.load()
    assert cassette.interactions == []


def test_cassette_record_and_play(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    # Record
    cassette.record(
        method="GET",
        uri="https://api.example.com/users",
        request_headers={"content-type": ["application/json"]},
        request_body=None,
        status=200,
        response_headers={"content-type": ["application/json"]},
        response_body=b'{"users": []}',
    )

    # Play back
    response = cassette.play(
        "GET",
        "https://api.example.com/users",
        {"content-type": ["application/json"]},
        None,
    )
    assert response.status == 200


def test_cassette_play_no_match(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    # Create empty cassette file
    RustCassette().save(path)
    cassette.load()

    with pytest.raises(NoMatchError):
        cassette.play("GET", "https://nonexistent.com/", {}, None)


def test_cassette_save_persists(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "persist.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record(
        method="GET",
        uri="https://example.com/",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"ok",
    )
    cassette.save()

    # Reload
    cassette2 = Cassette(path, record_mode=RecordMode.NONE)
    cassette2.load()
    assert len(cassette2.interactions) == 1


def test_cassette_security_filtering_on_record(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "secure.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record(
        method="POST",
        uri="https://api.example.com/auth?api_key=supersecret",
        request_headers={"authorization": ["Bearer tok_secret"], "content-type": ["application/json"]},
        request_body=b'{"password": "mypassword"}',
        status=200,
        response_headers={"content-type": ["application/json"]},
        response_body=b'{"access_token": "new_token"}',
    )
    cassette.save()

    # Reload and verify filtering
    with open(path) as f:
        content = f.read()

    assert "tok_secret" not in content
    assert "supersecret" not in content
    assert "mypassword" not in content
    assert "new_token" not in content
    assert "FILTERED" in content


def test_record_mode_from_str() -> None:
    assert RecordMode.from_str("none") == RecordMode.NONE
    assert RecordMode.from_str("all") == RecordMode.ALL
    assert RecordMode.from_str("once") == RecordMode.ONCE
    assert RecordMode.from_str("new_episodes") == RecordMode.NEW_EPISODES
    assert RecordMode.from_str("new-episodes") == RecordMode.NEW_EPISODES
    assert RecordMode.from_str("rewrite") == RecordMode.REWRITE


def test_record_mode_from_str_invalid() -> None:
    with pytest.raises(ValueError, match="unknown record mode"):
        RecordMode.from_str("invalid")


def test_parse_duration_days() -> None:
    assert _parse_duration("30d") == timedelta(days=30)


def test_parse_duration_hours() -> None:
    assert _parse_duration("24h") == timedelta(hours=24)


def test_parse_duration_weeks() -> None:
    assert _parse_duration("4w") == timedelta(weeks=4)


def test_parse_duration_invalid_unit() -> None:
    with pytest.raises(ValueError, match="invalid duration string"):
        _parse_duration("10m")


def test_parse_duration_invalid_format() -> None:
    with pytest.raises(ValueError, match="invalid duration string"):
        _parse_duration("abc")


def test_parse_duration_empty_string() -> None:
    with pytest.raises(ValueError, match="invalid duration string"):
        _parse_duration("")


def _make_old_cassette(path: str, recorded_at: str) -> None:
    """Create a cassette file with a single interaction at the given timestamp."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at=recorded_at,
        )
    )
    c.save(path)


def test_expiry_no_expiry_when_max_age_none(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_not_expired(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2099-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="30d")
    cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_warn_on_expiry(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="warn")
    with pytest.warns(CassetteExpiredWarning, match="days old"):
        cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_fail_on_expiry(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="fail")
    with pytest.raises(CassetteExpiredError, match="days old"):
        cassette.load()


def test_expiry_rerecord_on_expiry(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="rerecord")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_empty_cassette_not_expired(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    RustCassette().save(path)

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_no_check_when_record_mode_all(tmp_path: Path) -> None:
    """RecordMode.ALL creates a fresh cassette, so expiry check never runs."""
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.ALL, max_age="1d", on_expiry="fail")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_no_check_when_file_missing(tmp_path: Path) -> None:
    """Missing file creates empty cassette, no expiry check."""
    path = os.path.join(str(tmp_path), "missing.yaml")

    cassette = Cassette(path, record_mode=RecordMode.ONCE, max_age="1d", on_expiry="fail")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_uses_newest_across_interaction_types(tmp_path: Path) -> None:
    """Expiry is based on the newest recorded_at across HTTP, gRPC, and WS interactions."""
    path = os.path.join(str(tmp_path), "mixed.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2020-01-01T00:00:00Z",
        )
    )
    c.add_grpc_interaction(
        GrpcInteraction(
            request=GrpcRequest("/svc/Method", {}, Body("text", "")),
            response=GrpcResponse(0, "OK", None, Body("text", "")),
            recorded_at="2020-06-01T00:00:00Z",
        )
    )
    c.add_ws_interaction(WsInteraction("wss://example.com", {}, [], "2020-03-01T00:00:00Z"))
    c.save(path)

    with pytest.warns(CassetteExpiredWarning):
        cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="warn")
        cassette.load()


# --- VCR format compatibility ---


def _write_vcr_cassette(path: str, interactions: list[dict[str, object]]) -> None:
    data = {"version": 1, "interactions": interactions}
    with open(path, "w") as f:
        yaml.dump(data, f)


def test_vcr_format_json_response(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://api.example.com/data",
                    "body": None,
                    "headers": {"Accept": ["application/json"]},
                },
                "response": {
                    "body": {"string": '{"key": "value", "num": 42}'},
                    "headers": {"Content-Type": ["application/json"]},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    assert len(c) == 1
    i = c.interactions[0]
    assert i.request.method == "GET"
    assert i.request.uri == "https://api.example.com/data"
    assert i.request.body.body_type == "none"
    assert i.response.status == 200
    assert i.response.body.body_type == "json"
    assert i.response.body.content == {"key": "value", "num": 42}


def test_vcr_format_text_response(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://example.com/page",
                    "body": None,
                    "headers": {},
                },
                "response": {
                    "body": {"string": "<html>hello</html>"},
                    "headers": {"Content-Type": ["text/html"]},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    i = c.interactions[0]
    assert i.response.body.body_type == "text"
    assert i.response.body.content == "<html>hello</html>"


def test_vcr_format_null_response_body(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "DELETE",
                    "uri": "https://example.com/resource/1",
                    "body": None,
                    "headers": {},
                },
                "response": {
                    "body": {"string": None},
                    "headers": {},
                    "status": {"code": 204, "message": "No Content"},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    assert c.interactions[0].response.status == 204
    assert c.interactions[0].response.body.body_type == "none"


def test_vcr_format_empty_string_request_body(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://example.com/",
                    "body": "",
                    "headers": {},
                },
                "response": {
                    "body": {"string": "ok"},
                    "headers": {},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    assert c.interactions[0].request.body.body_type == "none"


def test_vcr_format_string_request_body(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "POST",
                    "uri": "https://example.com/api",
                    "body": '{"prompt": "hello"}',
                    "headers": {"Content-Type": ["application/json"]},
                },
                "response": {
                    "body": {"string": '{"reply": "hi"}'},
                    "headers": {},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    i = c.interactions[0]
    assert i.request.body.body_type == "json"
    assert i.request.body.content == {"prompt": "hello"}
    assert i.response.body.body_type == "json"
    assert i.response.body.content == {"reply": "hi"}


def test_vcr_format_saves_as_cassetter(tmp_path: Path) -> None:
    vcr_path = os.path.join(str(tmp_path), "vcr.yaml")
    out_path = os.path.join(str(tmp_path), "out.yaml")
    _write_vcr_cassette(
        vcr_path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://example.com/",
                    "body": None,
                    "headers": {},
                },
                "response": {
                    "body": {"string": '{"ok": true}'},
                    "headers": {},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    c = RustCassette.load(vcr_path)
    c.save(out_path)

    with open(out_path) as f:
        saved = yaml.safe_load(f)

    # Verify saved format is cassetter, not VCR
    resp = saved["interactions"][0]["response"]
    assert resp["status"] == 200
    assert resp["body"]["type"] == "json"
    assert resp["body"]["content"] == {"ok": True}


def test_vcr_format_playback(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://api.example.com/users",
                    "body": None,
                    "headers": {"Accept": ["application/json"]},
                },
                "response": {
                    "body": {"string": '{"users": []}'},
                    "headers": {"Content-Type": ["application/json"]},
                    "status": {"code": 200, "message": "OK"},
                },
            }
        ],
    )
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    response = cassette.play("GET", "https://api.example.com/users", {}, None)
    assert response.status == 200
    assert response.body.content == {"users": []}


def test_vcr_format_parsed_body(tmp_path: Path) -> None:
    """pydantic-ai style serializer: structured `parsed_body` instead of `body`."""
    path = os.path.join(str(tmp_path), "parsed.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "POST",
                    "uri": "https://api.example.com/chat",
                    "headers": {"content-type": ["application/json"]},
                    "parsed_body": {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                },
                "response": {
                    "status": {"code": 200, "message": "OK"},
                    "headers": {"content-type": ["application/json"]},
                    "parsed_body": {"id": "abc", "choices": [{"message": {"content": "hello"}}]},
                },
            }
        ],
    )
    c = RustCassette.load(path)
    i = c.interactions[0]
    assert i.request.body.body_type == "json"
    assert i.request.body.content["model"] == "gpt-4o"
    assert i.response.body.body_type == "json"
    assert i.response.body.content["choices"][0]["message"]["content"] == "hello"


def test_vcr_format_missing_version(tmp_path: Path) -> None:
    """Cassettes written without a top-level version key load with version 1."""
    path = os.path.join(str(tmp_path), "no_version.yaml")
    data = {
        "interactions": [
            {
                "request": {"method": "GET", "uri": "https://example.com", "headers": {}},
                "response": {"status": {"code": 200, "message": "OK"}, "headers": {}},
            }
        ]
    }
    with open(path, "w") as f:
        yaml.dump(data, f)

    c = RustCassette.load(path)
    assert c.version == 1
    assert len(c) == 1


def test_parsed_body_saves_as_cassetter_format(tmp_path: Path) -> None:
    """parsed_body cassettes are rewritten in cassetter's own body format on save."""
    path = os.path.join(str(tmp_path), "parsed.yaml")
    _write_vcr_cassette(
        path,
        [
            {
                "request": {
                    "method": "GET",
                    "uri": "https://example.com",
                    "headers": {},
                    "parsed_body": {"q": 1},
                },
                "response": {"status": {"code": 200, "message": "OK"}, "headers": {}},
            }
        ],
    )
    c = RustCassette.load(path)
    out = os.path.join(str(tmp_path), "out.yaml")
    c.save(out)

    with open(out) as f:
        raw = yaml.safe_load(f)
    request = raw["interactions"][0]["request"]
    assert "parsed_body" not in request
    assert request["body"] == {"type": "json", "content": {"q": 1}}


def test_vcr_format_binary_body_and_headers(tmp_path: Path) -> None:
    """PyYAML !!binary scalars (bodies and header values) decode to real bytes."""
    path = os.path.join(str(tmp_path), "binary.yaml")
    data = {
        "interactions": [
            {
                "request": {"method": "GET", "uri": "https://example.com/stream", "headers": {}},
                "response": {
                    "status": {"code": 200, "message": "OK"},
                    "headers": {"content-type": [b"application/vnd.amazon.eventstream"]},
                    "body": {"string": b"\x00\x01\xffbinary-payload"},
                },
            }
        ]
    }
    with open(path, "w") as f:
        yaml.safe_dump(data, f)

    c = RustCassette.load(path)
    response = c.interactions[0].response
    assert response.headers["content-type"] == ["application/vnd.amazon.eventstream"]
    assert response.body.body_type == "binary"
    assert response.body.content == b"\x00\x01\xffbinary-payload"


def test_vcr_format_bare_mapping_request_body(tmp_path: Path) -> None:
    """A structured dict directly under request.body (aiohttp recordings) loads as JSON."""
    path = os.path.join(str(tmp_path), "mapping.yaml")
    data = {
        "interactions": [
            {
                "request": {
                    "method": "POST",
                    "uri": "https://example.com/chat",
                    "headers": {},
                    "body": {"model": "llama", "stream": False},
                },
                "response": {"status": {"code": 200, "message": "OK"}, "headers": {}},
            }
        ]
    }
    with open(path, "w") as f:
        yaml.safe_dump(data, f)

    c = RustCassette.load(path)
    body = c.interactions[0].request.body
    assert body.body_type == "json"
    assert body.content == {"model": "llama", "stream": False}


def test_match_config_rejects_unknown_matcher() -> None:
    with pytest.raises(ValueError, match="unknown matcher"):
        MatchConfig(match_on=["method", "url"])  # type: ignore[list-item]


def test_toml_save_refuses_grpc_interactions(tmp_path: Path) -> None:
    c = RustCassette()
    c.add_grpc_interaction(
        GrpcInteraction(
            GrpcRequest("/pkg.Svc/M", {}, Body("binary", b"\x01")),
            GrpcResponse(0, "OK", {}, Body("binary", b"\x02")),
            "2026-01-01T00:00:00Z",
        )
    )
    with pytest.raises(ValueError, match="TOML cassettes cannot store gRPC"):
        c.save(os.path.join(str(tmp_path), "grpc.toml"))


def test_saved_headers_are_sorted(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "sorted.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com", {"zebra": ["1"], "alpha": ["2"], "mid": ["3"]}),
            HttpResponse(200),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    with open(path) as f:
        text = f.read()
    assert text.index("alpha") < text.index("mid") < text.index("zebra")
    # deterministic across saves
    c.save(path)
    with open(path) as f:
        assert f.read() == text


def test_body_repr_multibyte_no_panic() -> None:
    body = Body("text", "é" * 40)
    assert repr(body)  # must not raise a panic across the FFI boundary


def test_scrub_multibyte_query_no_panic() -> None:
    interaction = HttpInteraction(
        HttpRequest("GET", "https://example.com/?%a€=1&api_key=x"),
        HttpResponse(200),
        "2026-01-01T00:00:00Z",
    )
    scrubbed = scrub_interaction(interaction, SecurityConfig())
    assert "api_key=[FILTERED]" in scrubbed.request.uri


def test_once_with_existing_cassette_is_replay_only(tmp_path: Path) -> None:
    """`once` must not record (or hit the network) when the cassette already exists."""
    path = os.path.join(str(tmp_path), "once.yaml")
    recorder = Cassette(path, record_mode=RecordMode.ALL)
    recorder.load()
    recorder.record(
        method="GET",
        uri="https://example.com/known",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"{}",
    )
    recorder.save()

    cassette = Cassette(path, record_mode=RecordMode.ONCE)
    cassette.load()
    assert cassette.can_record is False

    # Matched requests still replay
    assert cassette.play("GET", "https://example.com/known", {}, None).status == 200

    # Unmatched requests raise instead of recording
    with pytest.raises(NoMatchError):
        cassette.play("GET", "https://example.com/unknown", {}, None)


def test_once_without_cassette_records(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "fresh.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ONCE)
    cassette.load()
    assert cassette.can_record is True


def test_once_rerecord_expiry_allows_recording(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "expired.yaml")
    recorder = Cassette(path, record_mode=RecordMode.ALL)
    recorder.load()
    recorder.record(
        method="GET",
        uri="https://example.com",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"{}",
    )
    recorder.save()

    # Rewrite the recorded_at to be ancient
    with open(path) as f:
        content = f.read().replace(recorder.interactions[0].recorded_at, "2020-01-01T00:00:00+00:00")
    with open(path, "w") as f:
        f.write(content)

    cassette = Cassette(path, record_mode=RecordMode.ONCE, max_age="1d", on_expiry="rerecord")
    cassette.load()
    assert cassette.can_record is True


def test_play_matches_uri_with_filtered_query_param(tmp_path: Path) -> None:
    """Scrubbed query params must not break replay matching."""
    path = os.path.join(str(tmp_path), "filtered.yaml")
    recorder = Cassette(path, record_mode=RecordMode.ALL)
    recorder.load()
    recorder.record(
        method="GET",
        uri="https://example.com/data?api_key=super-secret&page=1",
        request_headers={"authorization": ["Bearer tok"]},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b'{"ok": true}',
    )
    recorder.save()

    # The stored URI is scrubbed
    stored_uri = recorder.interactions[0].request.uri
    assert "super-secret" not in stored_uri

    # Replay with the raw, unfiltered request must still match
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    response = cassette.play(
        "GET",
        "https://example.com/data?api_key=super-secret&page=1",
        {"authorization": ["Bearer tok"]},
        None,
    )
    assert response.status == 200


def test_play_matches_scrubbed_json_body(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "body_match.yaml")
    config = MatchConfig(match_on=["method", "uri", "json_body"])
    recorder = Cassette(path, record_mode=RecordMode.ALL, match_config=config)
    recorder.load()
    recorder.record(
        method="POST",
        uri="https://example.com/login",
        request_headers={"content-type": ["application/json"]},
        request_body=b'{"username": "alice", "password": "hunter2"}',
        status=200,
        response_headers={},
        response_body=b"{}",
    )
    recorder.save()

    cassette = Cassette(path, record_mode=RecordMode.NONE, match_config=config)
    cassette.load()
    response = cassette.play(
        "POST",
        "https://example.com/login",
        {"content-type": ["application/json"]},
        b'{"username": "alice", "password": "hunter2"}',
    )
    assert response.status == 200


def test_invalid_on_expiry_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid on_expiry"):
        Cassette(os.path.join(str(tmp_path), "x.yaml"), on_expiry="error")


def test_all_mode_truncates_stale_cassette(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "stale.yaml")
    recorder = Cassette(path, record_mode=RecordMode.ALL)
    recorder.load()
    recorder.record(
        method="GET",
        uri="https://example.com/old",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"{}",
    )
    recorder.save()
    assert len(RustCassette.load(path)) == 1

    # Re-record run that captures nothing must truncate the stale content
    rerecord = Cassette(path, record_mode=RecordMode.ALL)
    rerecord.load()
    rerecord.save()
    assert len(RustCassette.load(path)) == 0


def test_rewrite_mode_discards_recorded_interactions(tmp_path: Path) -> None:
    path = str(tmp_path / "stale.yaml")
    _save_interaction(path, "GET", "https://example.com/old", "old")
    assert len(RustCassette.load(path)) == 1

    rewrite = Cassette(path, record_mode=RecordMode.REWRITE)
    rewrite.load()
    assert rewrite.interactions == []
    assert rewrite.can_record is True
    rewrite.record(
        method="GET",
        uri="https://example.com/new",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"{}",
    )
    rewrite.save()

    written = RustCassette.load(path)
    assert [i.request.uri for i in written.interactions] == ["https://example.com/new"]


def test_rewrite_mode_leaves_no_file_when_nothing_is_recorded(tmp_path: Path) -> None:
    """Unlike `all`, which truncates, `rewrite` removes the cassette up front."""
    path = str(tmp_path / "stale.yaml")
    _save_interaction(path, "GET", "https://example.com/old", "old")

    rewrite = Cassette(path, record_mode=RecordMode.REWRITE)
    rewrite.load()
    rewrite.save()
    assert not os.path.exists(path)


def test_rewrite_mode_without_existing_cassette(tmp_path: Path) -> None:
    path = str(tmp_path / "missing.yaml")
    cassette = Cassette(path, record_mode=RecordMode.REWRITE)
    cassette.load()
    assert cassette.interactions == []
    cassette.save()
    assert not os.path.exists(path)


def test_save_preserves_file_permissions(tmp_path: Path) -> None:
    """Atomic save must keep a restrictive mode on an existing cassette."""
    if sys.platform == "win32":  # pragma: no cover
        pytest.skip("POSIX permissions only")

    path = os.path.join(str(tmp_path), "private.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(HttpRequest("GET", "https://example.com"), HttpResponse(200), "2026-01-01T00:00:00Z")
    )
    c.save(path)
    os.chmod(path, 0o600)

    c.add_interaction(
        HttpInteraction(HttpRequest("GET", "https://example.com/2"), HttpResponse(200), "2026-01-01T00:00:00Z")
    )
    c.save(path)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def _save_interaction(path: str, method: str, uri: str, body_text: str) -> None:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest(method, uri),
            response=HttpResponse(200, body=Body("text", body_text)),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)


def test_uri_normalizer_matches_normalized_equivalent(tmp_path: Path) -> None:
    """A normalizer applied to both sides lets region-variant URIs replay."""
    path = os.path.join(str(tmp_path), "regions.yaml")
    _save_interaction(path, "POST", "https://svc.us-east-2.example.com/model/m:0/run", "east-2")

    cassette = Cassette(
        path,
        record_mode=RecordMode.NONE,
        uri_normalizer=lambda uri: uri.replace("us-east-1", "REGION").replace("us-east-2", "REGION"),
    )
    cassette.load()

    response = cassette.play("POST", "https://svc.us-east-1.example.com/model/m:0/run", {}, None)
    assert response.body.content == "east-2"
    assert cassette.play_count == 1


def test_uri_normalizer_still_rejects_distinct_uris(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "distinct.yaml")
    _save_interaction(path, "GET", "https://svc.us-east-2.example.com/a", "a")

    cassette = Cassette(path, record_mode=RecordMode.NONE, uri_normalizer=lambda uri: uri.replace("us-east-2", "R"))
    cassette.load()

    with pytest.raises(NoMatchError):
        cassette.play("GET", "https://svc.us-east-2.example.com/other", {}, None)


def test_uri_normalizer_applies_to_recorded_interactions(tmp_path: Path) -> None:
    """An interaction recorded in this session is matchable through the normalizer."""
    path = os.path.join(str(tmp_path), "recorded.yaml")
    cassette = Cassette(
        path,
        record_mode=RecordMode.ALL,
        uri_normalizer=lambda uri: re.sub(r"account-\d+", "account-X", uri),
    )
    cassette.load()
    cassette.record(
        method="GET",
        uri="https://api.example.com/account-12345/items",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={},
        response_body=b"items",
    )

    response = cassette.play("GET", "https://api.example.com/account-99999/items", {}, None)
    assert response.body.content == "items"


def test_without_uri_normalizer_region_variant_does_not_match(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "no-normalizer.yaml")
    _save_interaction(path, "POST", "https://svc.us-east-2.example.com/run", "east-2")

    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    with pytest.raises(NoMatchError):
        cassette.play("POST", "https://svc.us-east-1.example.com/run", {}, None)


def test_corrupt_cassette_raises_cassette_load_error(tmp_path: Path) -> None:
    """A corrupt cassette surfaces as a library error, not a bare Rust ValueError."""
    path = os.path.join(str(tmp_path), "corrupt.yaml")
    with open(path, "w") as f:
        f.write("interactions: [{this is: not, valid: cassette")

    cassette = Cassette(path, record_mode=RecordMode.NONE)
    with pytest.raises(CassetteLoadError, match="could not parse cassette"):
        cassette.load()


def _record(cassette: Cassette, method: str, uri: str, body: bytes | None, reply: str) -> None:
    cassette.record(
        method=method,
        uri=uri,
        request_headers={"content-type": ["application/json"]},
        request_body=body,
        status=200,
        response_headers={},
        response_body=reply.encode(),
    )


def test_save_writes_interactions_in_canonical_order(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "canonical.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()
    _record(cassette, "GET", "https://api.example.com/b", None, "b")
    _record(cassette, "GET", "https://api.example.com/a", None, "a")
    cassette.save()

    saved = RustCassette.load(path)
    assert [i.request.uri for i in saved.interactions] == [
        "https://api.example.com/a",
        "https://api.example.com/b",
    ]


def test_save_keeps_order_the_matcher_relies_on(tmp_path: Path) -> None:
    """Interactions the matcher cannot tell apart must not be reordered.

    Replay takes the first unplayed match, so their order is what decides which
    response each request gets.
    """
    path = os.path.join(str(tmp_path), "ambiguous.yaml")
    uri = "https://api.example.com/chat"
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()
    _record(cassette, "POST", uri, b'{"q": "zebra"}', "first")
    _record(cassette, "POST", uri, b'{"q": "aardvark"}', "second")
    cassette.save()

    replayed = Cassette(path, record_mode=RecordMode.NONE)
    replayed.load()
    assert replayed.play("POST", uri, {}, b'{"q": "zebra"}').body.content == "first"


def test_save_sorts_by_body_when_it_is_matched_on(tmp_path: Path) -> None:
    """Matching on the body makes it safe to order by, so it is used."""
    path = os.path.join(str(tmp_path), "by-body.yaml")
    uri = "https://api.example.com/chat"
    cassette = Cassette(
        path,
        record_mode=RecordMode.ALL,
        match_config=MatchConfig(match_on=["method", "uri", "json_body"]),
    )
    cassette.load()
    _record(cassette, "POST", uri, b'{"q": "zebra"}', "zebra")
    _record(cassette, "POST", uri, b'{"q": "aardvark"}', "aardvark")
    cassette.save()

    saved = RustCassette.load(path)
    assert [i.response.body.content for i in saved.interactions] == ["aardvark", "zebra"]


def test_newly_recorded_interactions_follow_loaded_ones(tmp_path: Path) -> None:
    """An appended interaction sorts after the loaded one it ties with."""
    path = os.path.join(str(tmp_path), "appended.yaml")
    uri = "https://api.example.com/poll"
    seed = RustCassette()
    seed.add_interaction(
        HttpInteraction(HttpRequest("GET", uri), HttpResponse(200, body=Body("text", "loaded")), "2026-01-01T00:00:00Z")
    )
    seed.save(path)

    cassette = Cassette(path, record_mode=RecordMode.NEW_EPISODES)
    cassette.load()
    _record(cassette, "GET", uri, None, "appended")
    cassette.save()

    saved = RustCassette.load(path)
    assert [i.response.body.content for i in saved.interactions] == ["loaded", "appended"]


def test_uri_normalizer_collisions_keep_request_order(tmp_path: Path) -> None:
    """URIs the normalizer collapses into one must not be split by the sort.

    Matching compares the normalized URI, so these two are interchangeable at
    replay and their order is what picks the response - ordering by the raw URI
    they were recorded with would swap them.
    """
    path = os.path.join(str(tmp_path), "regions.yaml")

    def normalize(uri: str) -> str:
        return re.sub(r"us-east-\d", "REGION", uri)

    cassette = Cassette(path, record_mode=RecordMode.ALL, uri_normalizer=normalize)
    cassette.load()
    for region, reply in (("us-east-2", "sent-first"), ("us-east-1", "sent-second")):
        _record(cassette, "GET", f"https://svc.{region}.example.com/run", None, reply)
    cassette.save()

    assert [i.response.body.content for i in RustCassette.load(path).interactions] == ["sent-first", "sent-second"]

    replayed = Cassette(path, record_mode=RecordMode.NONE, uri_normalizer=normalize)
    replayed.load()
    assert replayed.play("GET", "https://svc.us-east-1.example.com/run", {}, None).body.content == "sent-first"
