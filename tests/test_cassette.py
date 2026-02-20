from __future__ import annotations

import os

import pytest

from vcr_but_better._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from vcr_but_better.cassette import Cassette, CassetteNotFoundError, NoMatchError
from vcr_but_better.recording import RecordMode


class TestRustCassette:
    def test_create_empty(self) -> None:
        c = RustCassette()
        assert c.version == 1
        assert len(c) == 0
        assert c.unplayed_count == 0

    def test_add_interaction(self) -> None:
        c = RustCassette()
        interaction = HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2026-01-01T00:00:00Z",
        )
        c.add_interaction(interaction)
        assert len(c) == 1
        assert c.unplayed_count == 1

    def test_mark_played(self) -> None:
        c = RustCassette()
        interaction = HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200),
            recorded_at="2026-01-01T00:00:00Z",
        )
        c.add_interaction(interaction)
        c.mark_played(0)
        assert c.unplayed_count == 0

    def test_save_and_load(self, tmp_path: object) -> None:
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

    def test_load_nonexistent(self) -> None:
        with pytest.raises(FileNotFoundError):
            RustCassette.load("/nonexistent/path.yaml")


class TestCassetteWrapper:
    def test_record_mode_none_missing_file(self) -> None:
        cassette = Cassette("/nonexistent.yaml", record_mode=RecordMode.NONE)
        with pytest.raises(CassetteNotFoundError):
            cassette.load()

    def test_record_mode_once_creates_new(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "new.yaml")
        cassette = Cassette(path, record_mode=RecordMode.ONCE)
        cassette.load()
        assert cassette.interactions == []

    def test_record_and_play(self, tmp_path: object) -> None:
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

    def test_play_no_match(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "empty.yaml")
        cassette = Cassette(path, record_mode=RecordMode.NONE)
        # Create empty cassette file
        RustCassette().save(path)
        cassette.load()

        with pytest.raises(NoMatchError):
            cassette.play("GET", "https://nonexistent.com/", {}, None)

    def test_save_persists(self, tmp_path: object) -> None:
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

    def test_security_filtering_on_record(self, tmp_path: object) -> None:
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


class TestRecordMode:
    def test_from_str(self) -> None:
        assert RecordMode.from_str("none") == RecordMode.NONE
        assert RecordMode.from_str("all") == RecordMode.ALL
        assert RecordMode.from_str("once") == RecordMode.ONCE
        assert RecordMode.from_str("new_episodes") == RecordMode.NEW_EPISODES
        assert RecordMode.from_str("new-episodes") == RecordMode.NEW_EPISODES

    def test_from_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="unknown record mode"):
            RecordMode.from_str("invalid")
