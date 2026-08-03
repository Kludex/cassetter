from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from cassetter import Cassetter
from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import CassetteExpiredError, CassetteExpiredWarning
from cassetter.recording import RecordMode

pytest_plugins = ("anyio",)


def _make_cassette(path: str) -> str:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/api"),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"ok": True})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    return path


def test_defaults_match_use_cassette() -> None:
    cassette = Cassetter().cassette("test.yaml")
    assert cassette.path == "test.yaml"
    assert cassette.record_mode == RecordMode.ONCE


def test_cassette_library_dir_is_joined() -> None:
    library_dir = os.path.join("tests", "cassettes")
    cassette = Cassetter(cassette_library_dir=library_dir).cassette("openai.yaml")
    assert cassette.path == os.path.join(library_dir, "openai.yaml")


def test_cassette_library_dir_accepts_path_like(tmp_path: Path) -> None:
    cassette = Cassetter(cassette_library_dir=tmp_path).cassette("openai.yaml")
    assert cassette.path == str(tmp_path / "openai.yaml")


def test_absolute_name_ignores_cassette_library_dir(tmp_path: Path) -> None:
    absolute = str(tmp_path / "openai.yaml")
    assert Cassetter(cassette_library_dir="tests/cassettes").cassette(absolute).path == absolute


def test_record_mode_accepts_string_and_enum() -> None:
    assert Cassetter(record_mode="all").cassette("test.yaml").record_mode == RecordMode.ALL
    assert Cassetter(record_mode=RecordMode.NEW_EPISODES).cassette("test.yaml").record_mode == RecordMode.NEW_EPISODES


def test_on_expiry_is_honored(tmp_path: Path) -> None:
    path = _make_cassette(str(tmp_path / "test.yaml"))
    recorder = Cassetter(record_mode="none", max_age="1h", on_expiry="fail")
    with pytest.raises(CassetteExpiredError):
        recorder.cassette(path).load()


@pytest.mark.anyio
async def test_use_cassette_replays_from_library_dir(tmp_path: Path) -> None:
    _make_cassette(str(tmp_path / "test.yaml"))
    recorder = Cassetter(cassette_library_dir=tmp_path, record_mode="none")

    with recorder.use_cassette("test.yaml") as cassette:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")

    assert response.status_code == 200
    assert cassette.all_played


@pytest.mark.anyio
async def test_call_is_an_alias_for_use_cassette(tmp_path: Path) -> None:
    _make_cassette(str(tmp_path / "test.yaml"))
    recorder = Cassetter(cassette_library_dir=tmp_path, record_mode="none", intercept=["httpx"])

    with recorder("test.yaml"):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")

    assert response.status_code == 200


def test_overrides_apply_to_a_single_cassette(tmp_path: Path) -> None:
    _make_cassette(str(tmp_path / "test.yaml"))
    recorder = Cassetter(cassette_library_dir=tmp_path, record_mode="none")

    with pytest.warns(CassetteExpiredWarning):
        with recorder.use_cassette("test.yaml", max_age="1h"):
            pass

    assert recorder.max_age is None
    with recorder.use_cassette("test.yaml"):
        pass


def test_unknown_override_is_rejected(tmp_path: Path) -> None:
    recorder = Cassetter(cassette_library_dir=tmp_path)
    with pytest.raises(TypeError):
        with recorder.use_cassette("test.yaml", nonexistent=True):
            pass  # pragma: no cover


def test_configuration_is_frozen() -> None:
    recorder = Cassetter(record_mode="none")
    with pytest.raises(AttributeError):
        recorder.record_mode = "all"  # type: ignore[misc]
