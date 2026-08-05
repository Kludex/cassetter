from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter._state import acquire_patches, installed
from cassetter.cassette import CassetteExpiredWarning
from cassetter.context import use_cassette
from cassetter.intercept._registry import _AUTO_DETECT_ORDER, _INTERCEPTOR_MAP, resolve_interceptors
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


@pytest.mark.anyio
async def test_use_cassette_with_filter_headers(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode="none", filter_headers=["x-custom"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_use_cassette_with_filter_query_parameters(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode="none", filter_query_parameters=["token"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_use_cassette_with_body_scrub_patterns(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode="none", body_scrub_patterns=["secret"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_use_cassette_with_filter_replacement(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode="none", filter_replacement="[REDACTED]"):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_use_cassette_string_record_mode(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode="none"):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_use_cassette_enum_record_mode(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with use_cassette(path, record_mode=RecordMode.NONE):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api")
    assert response.status_code == 200


def test_resolve_interceptors_unknown_interceptor() -> None:
    with pytest.raises(ValueError, match="unknown interceptor"):
        resolve_interceptors(["nonexistent"])


def test_resolve_interceptors_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_INTERCEPTOR_MAP, "aiohttp", None)
    with pytest.raises(ImportError, match="requires installing"):
        resolve_interceptors(["aiohttp"])


def test_resolve_interceptors_httpx() -> None:
    interceptors = resolve_interceptors(["httpx"])
    assert len(interceptors) == 1


def test_resolve_interceptors_multiple() -> None:
    interceptors = resolve_interceptors(["httpx", "aiohttp", "requests"])
    assert len(interceptors) == 3


def test_resolve_interceptors_auto_detect() -> None:
    interceptors = resolve_interceptors()
    assert len(interceptors) >= 1


def test_resolve_interceptors_auto_detect_none_arg() -> None:
    interceptors = resolve_interceptors(None)
    assert len(interceptors) >= 1


def test_resolve_interceptors_auto_detect_no_interceptors(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTO_DETECT_ORDER:
        monkeypatch.setitem(_INTERCEPTOR_MAP, name, None)
    with pytest.raises(ImportError, match="no HTTP interceptors available"):
        resolve_interceptors()


@pytest.mark.anyio
async def test_use_cassette_expired_warns(tmp_path: Path) -> None:
    path = _make_cassette(f"{tmp_path}/test.yaml")
    with pytest.warns(CassetteExpiredWarning):
        with use_cassette(path, record_mode="none", max_age="1h", on_expiry="warn"):
            pass


def test_resolve_interceptors_honors_explicit_list() -> None:
    """An explicit list installs exactly what was requested, even overlapping ones."""
    resolved = resolve_interceptors(["requests", "urllib3"])
    assert resolved == [_INTERCEPTOR_MAP["requests"], _INTERCEPTOR_MAP["urllib3"]]


def test_auto_detect_excludes_requests() -> None:
    """Auto-detect never installs requests (it overlaps urllib3)."""
    resolved = resolve_interceptors()
    assert _INTERCEPTOR_MAP["requests"] not in resolved


def test_acquire_patches_rolls_back_on_failure() -> None:
    events: list[str] = []

    class GoodInterceptor:
        def install(self) -> None:
            events.append("good-install")

        def uninstall(self) -> None:
            events.append("good-uninstall")

    class BadInterceptor:
        def install(self) -> None:
            raise RuntimeError("boom")

        def uninstall(self) -> None:  # pragma: no cover
            events.append("bad-uninstall")

    with pytest.raises(RuntimeError, match="boom"):
        acquire_patches([GoodInterceptor, BadInterceptor])

    assert events == ["good-install", "good-uninstall"]
    assert GoodInterceptor not in installed
    assert BadInterceptor not in installed
