"""High-level coverage of interceptor bypass, hooks, and body handling.

Every test drives a real client through the public `use_cassette` API. Bypass
paths pass through to a refused local port (proving the cassette was skipped);
hook paths rewrite the request to match a preloaded interaction so no network
is touched.
"""

from __future__ import annotations

import os

import pytest

from cassetter import RawRequest, SkipRecording
from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.context import use_cassette

pytest_plugins = ("anyio",)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_REFUSED = "http://127.0.0.1:1/"


def _preload(path: str, uri: str) -> None:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", uri, {}),
            HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"ok": True})),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)


def _rewrite_to(target: str) -> object:
    def hook(request: RawRequest) -> RawRequest:
        request.uri = target
        return request

    return hook


# --- requests ---


def test_requests_bypass_passes_through(tmp_path: object) -> None:
    import requests

    path = os.path.join(str(tmp_path), "req_bypass.yaml")
    _preload(path, "http://example.com/x")
    with use_cassette(path, record_mode="none", intercept=["requests"], ignore_localhost=True):
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get(_REFUSED)


def test_requests_hook_rewrites_to_match(tmp_path: object) -> None:
    import requests

    path = os.path.join(str(tmp_path), "req_hook.yaml")
    _preload(path, "https://api.example.com/real")
    with use_cassette(
        path,
        record_mode="none",
        intercept=["requests"],
        before_record_request=_rewrite_to("https://api.example.com/real"),
    ):
        resp = requests.get("https://api.example.com/original")
    assert resp.status_code == 200


def test_requests_hook_skip_recording_passes_through(tmp_path: object) -> None:
    import requests

    def hook(request: RawRequest) -> RawRequest:
        raise SkipRecording

    path = os.path.join(str(tmp_path), "req_skip.yaml")
    with use_cassette(path, record_mode="all", intercept=["requests"], before_record_request=hook):
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get(_REFUSED)


# --- urllib3 ---


def test_urllib3_bypass_passes_through(tmp_path: object) -> None:
    import urllib3

    path = os.path.join(str(tmp_path), "u3_bypass.yaml")
    _preload(path, "http://example.com/x")
    with use_cassette(path, record_mode="none", intercept=["urllib3"], ignore_localhost=True):
        with pytest.raises((urllib3.exceptions.HTTPError, OSError)):
            urllib3.PoolManager().request("GET", _REFUSED, retries=False)


def test_urllib3_hook_rewrites_to_match(tmp_path: object) -> None:
    import urllib3

    path = os.path.join(str(tmp_path), "u3_hook.yaml")
    _preload(path, "https://api.example.com/real")
    with use_cassette(
        path,
        record_mode="none",
        intercept=["urllib3"],
        before_record_request=_rewrite_to("https://api.example.com/real"),
    ):
        resp = urllib3.PoolManager().request("GET", "https://api.example.com/original")
    assert resp.status == 200


# --- aiohttp ---


@pytest.mark.anyio
async def test_aiohttp_bypass_passes_through(tmp_path: object) -> None:
    import aiohttp

    path = os.path.join(str(tmp_path), "aio_bypass.yaml")
    _preload(path, "http://example.com/x")
    with use_cassette(path, record_mode="none", intercept=["aiohttp"], ignore_localhost=True):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientError):
                await session.get(_REFUSED)


@pytest.mark.anyio
async def test_aiohttp_hook_rewrites_to_match(tmp_path: object) -> None:
    import aiohttp

    path = os.path.join(str(tmp_path), "aio_hook.yaml")
    _preload(path, "https://api.example.com/real")
    with use_cassette(
        path,
        record_mode="none",
        intercept=["aiohttp"],
        before_record_request=_rewrite_to("https://api.example.com/real"),
    ):
        async with aiohttp.ClientSession() as session:
            resp = await session.get("https://api.example.com/original")
    assert resp.status == 200


# --- pyreqwest ---


def test_pyreqwest_bypass_passes_through(tmp_path: object) -> None:
    import pyreqwest_impersonate as pri

    path = os.path.join(str(tmp_path), "prq_bypass.yaml")
    _preload(path, "http://example.com/x")
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"], ignore_localhost=True):
        with pytest.raises(Exception):
            pri.Client().get(_REFUSED)


def test_pyreqwest_hook_rewrites_to_match(tmp_path: object) -> None:
    import pyreqwest_impersonate as pri

    path = os.path.join(str(tmp_path), "prq_hook.yaml")
    _preload(path, "https://api.example.com/real")
    with use_cassette(
        path,
        record_mode="none",
        intercept=["pyreqwest"],
        before_record_request=_rewrite_to("https://api.example.com/real"),
    ):
        resp = pri.Client().get("https://api.example.com/original")
    assert resp.status_code == 200


def test_pyreqwest_replay_with_bytes_body(tmp_path: object) -> None:
    """A bytes `data=` body exercises extract_body's bytes branch."""
    import pyreqwest_impersonate as pri

    path = os.path.join(str(tmp_path), "prq_body.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("POST", "https://api.example.com/post", {}),
            HttpResponse(200, {}, Body("json", {"ok": True})),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    with use_cassette(path, record_mode="none", intercept=["pyreqwest"]):
        resp = pri.Client().post("https://api.example.com/post", data=b"raw-bytes")
    assert resp.status_code == 200


def test_urllib3_hook_skip_recording_passes_through(tmp_path: object) -> None:
    import urllib3

    def hook(request: RawRequest) -> RawRequest:
        raise SkipRecording

    path = os.path.join(str(tmp_path), "u3_skip.yaml")
    with use_cassette(path, record_mode="all", intercept=["urllib3"], before_record_request=hook):
        with pytest.raises((urllib3.exceptions.HTTPError, OSError)):
            urllib3.PoolManager().request("GET", _REFUSED, retries=False)


@pytest.mark.anyio
async def test_aiohttp_hook_skip_recording_passes_through(tmp_path: object) -> None:
    import aiohttp

    def hook(request: RawRequest) -> RawRequest:
        raise SkipRecording

    path = os.path.join(str(tmp_path), "aio_skip.yaml")
    with use_cassette(path, record_mode="all", intercept=["aiohttp"], before_record_request=hook):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientError):
                await session.get(_REFUSED)


def test_pyreqwest_hook_skip_recording_passes_through(tmp_path: object) -> None:
    import pyreqwest_impersonate as pri

    def hook(request: RawRequest) -> RawRequest:
        raise SkipRecording

    path = os.path.join(str(tmp_path), "prq_skip.yaml")
    with use_cassette(path, record_mode="all", intercept=["pyreqwest"], before_record_request=hook):
        with pytest.raises(Exception):
            pri.Client().get(_REFUSED)


@pytest.mark.anyio
async def test_httpx_async_hook_rewrites_to_match(tmp_path: object) -> None:
    import httpx

    path = os.path.join(str(tmp_path), "hx_hook.yaml")
    _preload(path, "https://api.example.com/real")
    with use_cassette(
        path,
        record_mode="none",
        intercept=["httpx"],
        before_record_request=_rewrite_to("https://api.example.com/real"),
    ):
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.example.com/original")
    assert resp.status_code == 200
