from __future__ import annotations

import os

import httpx
import pytest

from vcr_but_better._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from vcr_but_better.cassette import Cassette, NoMatchError
from vcr_but_better.context import use_cassette
from vcr_but_better.recording import RecordMode

pytest_plugins = ("anyio",)


@pytest.fixture
def cassette_path(tmp_path: object) -> str:
    return os.path.join(str(tmp_path), "httpx_test.yaml")


@pytest.fixture
def preloaded_cassette(cassette_path: str) -> str:
    """Create a cassette file with a pre-recorded interaction."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest(
                "GET",
                "https://httpbin.org/get",
                {"host": ["httpbin.org"]},
            ),
            response=HttpResponse(
                200,
                {"content-type": ["application/json"]},
                Body("json", {"origin": "127.0.0.1", "url": "https://httpbin.org/get"}),
            ),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(cassette_path)
    return cassette_path


@pytest.mark.anyio
async def test_replay_from_cassette(preloaded_cassette: str) -> None:
    async with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")

    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "127.0.0.1"


@pytest.mark.anyio
async def test_no_match_raises(preloaded_cassette: str) -> None:
    async with use_cassette(preloaded_cassette, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            with pytest.raises(NoMatchError):
                await client.get("https://httpbin.org/post")


@pytest.mark.anyio
async def test_record_and_replay(cassette_path: str) -> None:
    """Test that we can record an interaction and then replay it."""
    # Create cassette with recording
    cassette = Cassette(cassette_path, record_mode=RecordMode.ALL)
    cassette.load()

    cassette.record(
        method="GET",
        uri="https://example.com/api/data",
        request_headers={},
        request_body=None,
        status=200,
        response_headers={"content-type": ["application/json"]},
        response_body=b'{"items": [1, 2, 3]}',
    )
    cassette.save()

    # Replay
    async with use_cassette(cassette_path, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            response = await client.get("https://example.com/api/data")

    assert response.status_code == 200
    assert response.json() == {"items": [1, 2, 3]}
