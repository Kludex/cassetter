from __future__ import annotations

import json
import os
from collections import Counter

from cassetter import RecordedRequest
from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette
from cassetter.recording import RecordMode


def _make_cassette(tmp_path: object) -> Cassette:
    path = os.path.join(str(tmp_path), "introspection.yaml")
    inner = RustCassette()
    inner.add_interaction(
        HttpInteraction(
            HttpRequest(
                "POST",
                "https://api.example.com/v1/items?b=2&a=1",
                {"content-type": ["application/json"]},
                Body("json", {"name": "widget", "tags": ["a", "b"]}),
            ),
            HttpResponse(200, {}, Body("json", {"ok": True})),
            "2026-01-01T00:00:00Z",
        )
    )
    inner.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "http://api.example.com:8080/v2/status", {}, Body("text", "ping")),
            HttpResponse(200, {}, Body("text", "pong")),
            "2026-01-01T00:00:00Z",
        )
    )
    inner.save(path)
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    return cassette


def test_requests_exposes_vcr_attributes(tmp_path: object) -> None:
    cassette = _make_cassette(tmp_path)
    requests = cassette.requests

    assert len(requests) == 2
    first = requests[0]
    assert isinstance(first, RecordedRequest)
    assert first.method == "POST"
    assert first.uri == "https://api.example.com/v1/items?b=2&a=1"
    assert first.headers == {"content-type": ["application/json"]}
    assert json.loads(first.body) == {"name": "widget", "tags": ["a", "b"]}
    assert first.scheme == "https"
    assert first.host == "api.example.com"
    assert first.port == 443
    assert first.path == "/v1/items"
    assert first.query == [("a", "1"), ("b", "2")]

    second = requests[1]
    assert second.body == "ping"
    assert second.port == 8080
    assert second.query == []


def test_request_body_wire_forms(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "bodies.yaml")
    inner = RustCassette()
    for body in (Body("binary", b"\x00\x01"), Body("none")):
        inner.add_interaction(
            HttpInteraction(
                HttpRequest("POST", "https://example.com", {}, body),
                HttpResponse(200),
                "2026-01-01T00:00:00Z",
            )
        )
    inner.save(path)
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    assert cassette.requests[0].body == b"\x00\x01"
    assert cassette.requests[1].body is None


def test_play_count_lifecycle(tmp_path: object) -> None:
    cassette = _make_cassette(tmp_path)

    assert cassette.play_count == 0
    assert cassette.play_counts == Counter()
    assert not cassette.all_played

    cassette.play("POST", "https://api.example.com/v1/items?b=2&a=1", {}, None)
    assert cassette.play_count == 1
    assert cassette.play_counts == Counter({0: 1})
    assert not cassette.all_played

    cassette.play("GET", "http://api.example.com:8080/v2/status", {}, None)
    assert cassette.play_count == 2
    assert cassette.play_counts == Counter({0: 1, 1: 1})
    assert cassette.all_played


def test_introspection_before_load() -> None:
    cassette = Cassette("/tmp/never-loaded.yaml", record_mode=RecordMode.NONE)
    assert cassette.requests == []
    assert cassette.play_count == 0
    assert cassette.play_counts == Counter()
    # vcrpy semantics: an empty cassette counts as fully played
    assert cassette.all_played


def test_play_counts_track_repeats(tmp_path: object) -> None:
    """Replaying the same interaction twice (matcher fallback) counts both plays."""
    path = os.path.join(str(tmp_path), "repeats.yaml")
    inner = RustCassette()
    inner.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com/one", {}, Body("none")),
            HttpResponse(200, {}, Body("json", {"n": 1})),
            "2026-01-01T00:00:00Z",
        )
    )
    inner.save(path)
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()

    cassette.play("GET", "https://example.com/one", {}, None)
    cassette.play("GET", "https://example.com/one", {}, None)

    assert cassette.play_count == 2
    assert cassette.play_counts == Counter({0: 2})
    assert cassette.all_played
