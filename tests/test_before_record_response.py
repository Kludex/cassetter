from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, RawResponse, SkipRecording
from cassetter.context import use_cassette

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: Path) -> str:
    return os.path.join(str(tmp_path), "response_hook.yaml")


@pytest.mark.anyio
async def test_before_record_response_modifies_response(cassette_path: str) -> None:
    def strip_header(response: RawResponse) -> RawResponse:
        response.headers.pop("x-request-id", None)
        return response

    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"x-request-id": "abc123"}, json={"ok": True})
    )

    with use_cassette(cassette_path, record_mode="all", intercept=["httpx"], before_record_response=strip_header):
        async with httpx.AsyncClient(transport=mock_transport) as client:
            await client.get("https://api.example.com/data")

    # Load the saved cassette and verify the header was stripped
    saved = RustCassette.load(cassette_path)
    assert "x-request-id" not in saved.interactions[0].response.headers


@pytest.mark.anyio
async def test_before_record_response_skip_recording(cassette_path: str) -> None:
    def skip_errors(response: RawResponse) -> RawResponse:
        if response.status >= 500:
            raise SkipRecording
        return response  # pragma: no cover

    mock_transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))

    with use_cassette(cassette_path, record_mode="all", intercept=["httpx"], before_record_response=skip_errors):
        async with httpx.AsyncClient(transport=mock_transport) as client:
            await client.get("https://api.example.com/data")

    # Cassette file should not exist since the only interaction was skipped
    assert not os.path.exists(cassette_path)


@pytest.mark.anyio
async def test_before_record_response_modifies_status(cassette_path: str) -> None:
    def normalize_status(response: RawResponse) -> RawResponse:
        if response.status == 201:
            response.status = 200
        return response

    mock_transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"created": True}))

    with use_cassette(cassette_path, record_mode="all", intercept=["httpx"], before_record_response=normalize_status):
        async with httpx.AsyncClient(transport=mock_transport) as client:
            await client.get("https://api.example.com/data")

    saved = RustCassette.load(cassette_path)
    assert saved.interactions[0].response.status == 200


@pytest.mark.anyio
async def test_before_record_response_not_called_on_replay(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "replay.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://api.example.com/data"),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"ok": True})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)

    calls: list[RawResponse] = []

    def track_calls(response: RawResponse) -> RawResponse:
        calls.append(response)  # pragma: no cover
        return response  # pragma: no cover

    with use_cassette(path, record_mode="none", intercept=["httpx"], before_record_response=track_calls):
        async with httpx.AsyncClient() as client:
            await client.get("https://api.example.com/data")

    assert calls == []


def test_before_record_response_with_vcr_config(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")

    def my_hook(response: RawResponse) -> RawResponse:
        return response  # pragma: no cover

    cassette = Cassette(path, before_record_response=my_hook)
    assert cassette.before_record_response is my_hook


def test_before_record_response_default_is_none(tmp_path: Path) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = Cassette(path)
    assert cassette.before_record_response is None
