from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette
from cassetter.context import use_cassette
from cassetter.intercept._base import is_localhost

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: Path) -> str:
    return os.path.join(str(tmp_path), "ignore_localhost.yaml")


@pytest.fixture
def preloaded_cassette(cassette_path: str) -> str:
    """Create a cassette with a pre-recorded non-localhost interaction."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://api.example.com/data", {}),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"ok": True})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(cassette_path)
    return cassette_path


def test_is_localhost_with_localhost() -> None:
    assert is_localhost("http://localhost/path") is True


def test_is_localhost_with_port() -> None:
    assert is_localhost("http://localhost:8080/path") is True


def test_is_localhost_ipv4_loopback() -> None:
    assert is_localhost("http://127.0.0.1/path") is True


def test_is_localhost_ipv4_loopback_with_port() -> None:
    assert is_localhost("http://127.0.0.1:9000/api") is True


def test_is_localhost_ipv6_loopback_bracketed() -> None:
    assert is_localhost("http://[::1]/path") is True


def test_is_localhost_ipv6_loopback_bracketed_with_port() -> None:
    assert is_localhost("http://[::1]:8080/path") is True


def test_is_localhost_non_localhost() -> None:
    assert is_localhost("https://api.example.com/data") is False


def test_is_localhost_non_localhost_ip() -> None:
    assert is_localhost("http://192.168.1.1/data") is False


def test_is_localhost_empty_string() -> None:
    assert is_localhost("") is False


@pytest.mark.anyio
async def test_async_localhost_bypasses_cassette(cassette_path: str) -> None:
    """When ignore_localhost=True, localhost requests go to the real transport."""
    with use_cassette(cassette_path, record_mode="none", intercept=["httpx"], ignore_localhost=True) as cassette:
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(418, json={"teapot": True}))
        async with httpx.AsyncClient(transport=mock_transport) as client:
            response = await client.get("http://localhost:8080/health")
        assert response.status_code == 418
        assert response.json() == {"teapot": True}
        assert len(cassette.interactions) == 0


def test_sync_localhost_bypasses_cassette(cassette_path: str) -> None:
    """When ignore_localhost=True, sync localhost requests go to the real transport."""
    with use_cassette(cassette_path, record_mode="none", intercept=["httpx"], ignore_localhost=True) as cassette:
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(418, json={"teapot": True}))
        with httpx.Client(transport=mock_transport) as client:
            response = client.get("http://127.0.0.1:9000/health")
        assert response.status_code == 418
        assert response.json() == {"teapot": True}
        assert len(cassette.interactions) == 0


@pytest.mark.anyio
async def test_non_localhost_still_uses_cassette(preloaded_cassette: str) -> None:
    """Non-localhost requests still go through the cassette even with ignore_localhost=True."""
    with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"], ignore_localhost=True):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.example.com/data")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


@pytest.mark.anyio
async def test_localhost_without_flag_uses_cassette(cassette_path: str) -> None:
    """Default ignore_localhost=False means localhost requests go through the cassette."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "http://localhost:8080/health", {}),
            response=HttpResponse(200, {}, Body("json", {"status": "ok"})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(cassette_path)

    with use_cassette(cassette_path, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8080/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_ignore_localhost_property() -> None:
    cassette = Cassette("/tmp/test.yaml", ignore_localhost=True)
    assert cassette.ignore_localhost is True

    cassette_default = Cassette("/tmp/test.yaml")
    assert cassette_default.ignore_localhost is False
