from __future__ import annotations

import os
from datetime import timedelta

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
    WsInteraction,
)
from cassetter.cassette import (
    Cassette,
    CassetteExpiredError,
    CassetteExpiredWarning,
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


def test_rust_cassette_save_and_load(tmp_path: object) -> None:
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


def test_cassette_load_existing_file(tmp_path: object) -> None:
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


def test_record_mode_once_creates_new(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "new.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ONCE)
    cassette.load()
    assert cassette.interactions == []


def test_cassette_record_and_play(tmp_path: object) -> None:
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


def test_cassette_play_no_match(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "empty.yaml")
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    # Create empty cassette file
    RustCassette().save(path)
    cassette.load()

    with pytest.raises(NoMatchError):
        cassette.play("GET", "https://nonexistent.com/", {}, None)


def test_cassette_save_persists(tmp_path: object) -> None:
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


def test_cassette_security_filtering_on_record(tmp_path: object) -> None:
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


def test_expiry_no_expiry_when_max_age_none(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_not_expired(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2099-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="30d")
    cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_warn_on_expiry(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="warn")
    with pytest.warns(CassetteExpiredWarning, match="days old"):
        cassette.load()
    assert len(cassette.interactions) == 1


def test_expiry_fail_on_expiry(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="fail")
    with pytest.raises(CassetteExpiredError, match="days old"):
        cassette.load()


def test_expiry_rerecord_on_expiry(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d", on_expiry="rerecord")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_empty_cassette_not_expired(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    RustCassette().save(path)

    cassette = Cassette(path, record_mode=RecordMode.NONE, max_age="1d")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_no_check_when_record_mode_all(tmp_path: object) -> None:
    """RecordMode.ALL creates a fresh cassette, so expiry check never runs."""
    path = os.path.join(str(tmp_path), "test.yaml")
    _make_old_cassette(path, "2020-01-01T00:00:00Z")

    cassette = Cassette(path, record_mode=RecordMode.ALL, max_age="1d", on_expiry="fail")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_no_check_when_file_missing(tmp_path: object) -> None:
    """Missing file creates empty cassette, no expiry check."""
    path = os.path.join(str(tmp_path), "missing.yaml")

    cassette = Cassette(path, record_mode=RecordMode.ONCE, max_age="1d", on_expiry="fail")
    cassette.load()
    assert len(cassette.interactions) == 0


def test_expiry_uses_newest_across_interaction_types(tmp_path: object) -> None:
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


def test_vcr_format_json_response(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    c = RustCassette.load(path)
    assert len(c) == 1
    i = c.interactions[0]
    assert i.request.method == "GET"
    assert i.request.uri == "https://api.example.com/data"
    assert i.request.body.body_type == "none"
    assert i.response.status == 200
    assert i.response.body.body_type == "json"
    assert i.response.body.content == {"key": "value", "num": 42}


def test_vcr_format_text_response(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    c = RustCassette.load(path)
    i = c.interactions[0]
    assert i.response.body.body_type == "text"
    assert i.response.body.content == "<html>hello</html>"


def test_vcr_format_null_response_body(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    c = RustCassette.load(path)
    assert c.interactions[0].response.status == 204
    assert c.interactions[0].response.body.body_type == "none"


def test_vcr_format_empty_string_request_body(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    c = RustCassette.load(path)
    assert c.interactions[0].request.body.body_type == "none"


def test_vcr_format_string_request_body(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    c = RustCassette.load(path)
    i = c.interactions[0]
    assert i.request.body.body_type == "json"
    assert i.request.body.content == {"prompt": "hello"}
    assert i.response.body.body_type == "json"
    assert i.response.body.content == {"reply": "hi"}


def test_vcr_format_saves_as_cassetter(tmp_path: object) -> None:
    vcr_path = os.path.join(str(tmp_path), "vcr.yaml")
    out_path = os.path.join(str(tmp_path), "out.yaml")
    _write_vcr_cassette(vcr_path, [{
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
    }])
    c = RustCassette.load(vcr_path)
    c.save(out_path)

    with open(out_path) as f:
        saved = yaml.safe_load(f)

    # Verify saved format is cassetter, not VCR
    resp = saved["interactions"][0]["response"]
    assert resp["status"] == 200
    assert resp["body"]["type"] == "json"
    assert resp["body"]["content"] == {"ok": True}


def test_vcr_format_playback(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "vcr.yaml")
    _write_vcr_cassette(path, [{
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
    }])
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    response = cassette.play("GET", "https://api.example.com/users", {}, None)
    assert response.status == 200
    assert response.body.content == {"users": []}
