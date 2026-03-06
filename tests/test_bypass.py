from __future__ import annotations

import os

import httpx
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import BypassCassette, Cassette, RawRequest
from cassetter.context import use_cassette

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: object) -> str:
    return os.path.join(str(tmp_path), "bypass.yaml")


@pytest.fixture
def preloaded_cassette(cassette_path: str) -> str:
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


@pytest.mark.anyio
async def test_matching_host_bypasses_cassette(cassette_path: str) -> None:
    with use_cassette(cassette_path, record_mode="none", intercept=["httpx"], ignore_hosts=["*.googleapis.com"]):
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"token": "abc"}))
        async with httpx.AsyncClient(transport=mock_transport) as client:
            response = await client.get("https://oauth2.googleapis.com/token")
        assert response.status_code == 200
        assert response.json() == {"token": "abc"}


@pytest.mark.anyio
async def test_non_matching_host_uses_cassette(preloaded_cassette: str) -> None:
    with use_cassette(
        preloaded_cassette, record_mode="none", intercept=["httpx"], ignore_hosts=["*.googleapis.com"]
    ):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.example.com/data")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


@pytest.mark.anyio
async def test_multiple_ignore_patterns(cassette_path: str) -> None:
    with use_cassette(
        cassette_path,
        record_mode="none",
        intercept=["httpx"],
        ignore_hosts=["*.googleapis.com", "accounts.google.com"],
    ):
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(204))
        async with httpx.AsyncClient(transport=mock_transport) as client:
            r1 = await client.get("https://oauth2.googleapis.com/token")
            r2 = await client.get("https://accounts.google.com/o/oauth2/auth")
        assert r1.status_code == 204
        assert r2.status_code == 204


def test_should_bypass_with_ignore_hosts() -> None:
    cassette = Cassette("/tmp/test.yaml", ignore_hosts=["*.example.com", "specific.host.io"])
    assert cassette.should_bypass("https://api.example.com/data") is True
    assert cassette.should_bypass("https://specific.host.io/path") is True
    assert cassette.should_bypass("https://other.com/path") is False


def test_should_bypass_combines_localhost_and_ignore_hosts() -> None:
    cassette = Cassette("/tmp/test.yaml", ignore_localhost=True, ignore_hosts=["*.googleapis.com"])
    assert cassette.should_bypass("http://localhost:8080/health") is True
    assert cassette.should_bypass("https://oauth2.googleapis.com/token") is True
    assert cassette.should_bypass("https://api.example.com/data") is False


@pytest.mark.anyio
async def test_bypass_cassette_exception_passes_through(cassette_path: str) -> None:
    def hook(request: RawRequest) -> None:
        if "googleapis.com" in request.uri:
            raise BypassCassette

    with use_cassette(
        cassette_path, record_mode="none", intercept=["httpx"], before_record_request=hook
    ):
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"token": "xyz"}))
        async with httpx.AsyncClient(transport=mock_transport) as client:
            response = await client.get("https://oauth2.googleapis.com/token")
        assert response.status_code == 200
        assert response.json() == {"token": "xyz"}


@pytest.mark.anyio
async def test_hook_without_exception_uses_cassette(preloaded_cassette: str) -> None:
    calls: list[str] = []

    def hook(request: RawRequest) -> None:
        calls.append(request.uri)

    with use_cassette(
        preloaded_cassette, record_mode="none", intercept=["httpx"], before_record_request=hook
    ):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.example.com/data")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert calls == ["https://api.example.com/data"]


def test_sync_bypass_cassette_exception_passes_through(cassette_path: str) -> None:
    def hook(request: RawRequest) -> None:
        if "googleapis.com" in request.uri:
            raise BypassCassette

    with use_cassette(
        cassette_path, record_mode="none", intercept=["httpx"], before_record_request=hook
    ):
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"token": "xyz"}))
        with httpx.Client(transport=mock_transport) as client:
            response = client.get("https://oauth2.googleapis.com/token")
        assert response.status_code == 200
        assert response.json() == {"token": "xyz"}


@pytest.mark.anyio
async def test_hook_receives_correct_arguments(preloaded_cassette: str) -> None:
    captured: list[RawRequest] = []

    def hook(request: RawRequest) -> None:
        captured.append(request)

    with use_cassette(
        preloaded_cassette, record_mode="none", intercept=["httpx"], before_record_request=hook
    ):
        async with httpx.AsyncClient() as client:
            await client.get("https://api.example.com/data")
        assert len(captured) == 1
        assert captured[0].method == "GET"
        assert captured[0].uri == "https://api.example.com/data"
