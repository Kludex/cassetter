from __future__ import annotations

import os
from pathlib import Path

import httpx

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import RawRequest
from cassetter.context import use_cassette

URI = "https://api.example.com/chat"


def _recorded(tmp_path: Path, body: dict[str, object]) -> str:
    path = os.path.join(str(tmp_path), "chat.yaml")
    cassette = RustCassette()
    cassette.add_interaction(
        HttpInteraction(
            HttpRequest("POST", URI, {"content-type": ["application/json"]}, Body("json", body)),
            HttpResponse(200, body=Body("text", "ok")),
            "2026-01-01T00:00:00Z",
        )
    )
    cassette.save(path)
    return path


def _echo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=request.content)


def test_replay_captures_what_the_code_sends_now(tmp_path: Path) -> None:
    """The default matcher ignores the body, so only `sent_requests` shows the code changed what it sends."""
    path = _recorded(tmp_path, {"model": "old"})

    with use_cassette(path, record_mode="none", intercept=["httpx"]) as cassette:
        httpx.post(URI, json={"model": "new"}, headers={"x-feature": "on"})

    assert [request.body for request in cassette.requests] == ['{"model": "old"}']
    [sent] = cassette.sent_requests
    assert (sent.method, sent.uri, sent.body) == ("POST", URI, '{"model":"new"}')
    assert sent.headers["x-feature"] == ["on"]
    assert sent.path == "/chat"


def test_live_requests_are_captured_while_recording(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "live.yaml")

    with use_cassette(path, record_mode="all", intercept=["httpx"]) as cassette:
        with httpx.Client(transport=httpx.MockTransport(_echo)) as client:
            for turn in ("first", "second"):
                client.post(URI, json={"turn": turn})

    assert [request.body for request in cassette.sent_requests] == ['{"turn":"first"}', '{"turn":"second"}']


def test_captured_before_hooks_and_scrubbing(tmp_path: Path) -> None:
    """The hook and the default header filter shape the recording, not what the code sent."""
    path = os.path.join(str(tmp_path), "hooked.yaml")

    def redact(request: RawRequest) -> RawRequest:
        return RawRequest(request.method, request.uri, request.headers, b'{"secret":"[REDACTED]"}')

    with use_cassette(path, record_mode="all", intercept=["httpx"], before_record_request=redact) as cassette:
        with httpx.Client(transport=httpx.MockTransport(_echo)) as client:
            client.post(URI, json={"secret": "s3cr3t"}, headers={"authorization": "Bearer sk-live"})

    [sent] = cassette.sent_requests
    assert sent.body == '{"secret":"s3cr3t"}'
    assert sent.headers["authorization"] == ["Bearer sk-live"]
    [recorded] = cassette.requests
    assert recorded.body == '{"secret": "[REDACTED]"}'
    assert "authorization" not in recorded.headers


def test_bypassed_requests_are_not_captured(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "bypass.yaml")

    with use_cassette(path, record_mode="all", intercept=["httpx"], ignore_hosts=["api.example.com"]) as cassette:
        with httpx.Client(transport=httpx.MockTransport(_echo)) as client:
            client.post(URI, json={})

    assert cassette.sent_requests == []


def test_binary_and_empty_bodies(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "bodies.yaml")

    with use_cassette(path, record_mode="all", intercept=["httpx"]) as cassette:
        with httpx.Client(transport=httpx.MockTransport(_echo)) as client:
            client.post(URI, content=b"\xff\xfe")
            client.get(URI)

    assert [request.body for request in cassette.sent_requests] == [b"\xff\xfe", None]


def test_loading_starts_a_new_list(tmp_path: Path) -> None:
    path = _recorded(tmp_path, {})

    with use_cassette(path, record_mode="none", intercept=["httpx"]) as cassette:
        httpx.post(URI, json={})
        cassette.load()

    assert cassette.sent_requests == []
