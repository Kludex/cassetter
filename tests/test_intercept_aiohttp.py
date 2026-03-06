from __future__ import annotations

import os

import aiohttp
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cassette import Cassette, NoMatchError
from cassetter.intercept._aiohttp import (
    AiohttpInterceptor,
    _build_aiohttp_response,
    _extract_request_body,
    _extract_request_headers,
    _extract_response_headers,
)
from cassetter.recording import RecordMode

pytest_plugins = ("anyio",)


@pytest.fixture
def anyio_backend() -> str:
    """aiohttp only supports asyncio."""
    return "asyncio"


def _preload_cassette(path: str) -> Cassette:
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/api"),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"data": "aiohttp"})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    cassette = Cassette(path, record_mode=RecordMode.NONE)
    cassette.load()
    return cassette


@pytest.mark.anyio
async def test_interceptor_replay(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = AiohttpInterceptor()
    interceptor.install(cassette)

    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get("https://example.com/api")
            body = await response.json(content_type=None)
            assert response.status == 200
            assert body == {"data": "aiohttp"}
    finally:
        interceptor.uninstall()


@pytest.mark.anyio
async def test_interceptor_no_match_cant_record(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = _preload_cassette(path)

    interceptor = AiohttpInterceptor()
    interceptor.install(cassette)

    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(NoMatchError):
                await session.get("https://example.com/unknown")
    finally:
        interceptor.uninstall()


@pytest.mark.anyio
async def test_interceptor_record(tmp_path: object) -> None:
    import asyncio
    from unittest.mock import patch

    from multidict import CIMultiDict, CIMultiDictProxy
    from yarl import URL

    path = os.path.join(str(tmp_path), "test.yaml")
    cassette = Cassette(path, record_mode=RecordMode.ALL)
    cassette.load()

    async def mock_request(
        session: aiohttp.ClientSession,
        method: str,
        str_or_url: object,
        **kwargs: object,
    ) -> aiohttp.ClientResponse:
        resp = aiohttp.ClientResponse(
            method=method,
            url=URL(str(str_or_url)),
            writer=None,  # type: ignore[arg-type]
            continue100=None,
            timer=None,  # type: ignore[arg-type]
            request_info=aiohttp.RequestInfo(
                url=URL(str(str_or_url)),
                method=method,
                headers=CIMultiDictProxy(CIMultiDict()),
                real_url=URL(str(str_or_url)),
            ),
            traces=[],
            loop=asyncio.get_running_loop(),
            session=None,  # type: ignore[arg-type]
        )
        resp.status = 200
        resp._headers = CIMultiDictProxy(CIMultiDict({"content-type": "application/json"}))  # type: ignore[assignment]
        resp._body = b'{"recorded": true}'  # type: ignore[assignment]
        return resp

    # Mock _request first, then install interceptor so the interceptor's
    # saved original_request points to our mock.
    with patch.object(aiohttp.ClientSession, "_request", mock_request):
        interceptor = AiohttpInterceptor()
        interceptor.install(cassette)
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get("https://example.com/new-endpoint")
                await response.read()
            assert response.status == 200
            assert len(cassette.interactions) == 1
        finally:
            interceptor.uninstall()


def test_interceptor_install_uninstall() -> None:
    interceptor = AiohttpInterceptor()
    original_request = aiohttp.ClientSession._request
    cassette = Cassette("/nonexistent", record_mode=RecordMode.NONE)
    cassette.load()

    interceptor.install(cassette)
    assert aiohttp.ClientSession._request is not original_request

    interceptor.uninstall()
    assert aiohttp.ClientSession._request is original_request


def test_extract_request_headers_from_dict() -> None:
    headers = _extract_request_headers({"Content-Type": "application/json", "Accept": "text/html"})
    assert headers == {"content-type": ["application/json"], "accept": ["text/html"]}


def test_extract_request_headers_none() -> None:
    assert _extract_request_headers(None) == {}


def test_extract_request_body_bytes_data() -> None:
    assert _extract_request_body({"data": b"hello"}) == b"hello"


def test_extract_request_body_str_data() -> None:
    assert _extract_request_body({"data": "hello"}) == b"hello"


def test_extract_request_body_json_data() -> None:
    result = _extract_request_body({"json": {"key": "value"}})
    assert result is not None
    assert b"key" in result


def test_extract_request_body_no_body() -> None:
    assert _extract_request_body({}) is None


def test_extract_request_body_none_data() -> None:
    assert _extract_request_body({"data": None}) is None


def test_extract_response_headers_multidict() -> None:
    from multidict import CIMultiDict, CIMultiDictProxy

    headers = CIMultiDictProxy(CIMultiDict([("Content-Type", "application/json"), ("X-Custom", "value")]))
    result = _extract_response_headers(headers)
    assert result == {"content-type": ["application/json"], "x-custom": ["value"]}


@pytest.mark.anyio
async def test_build_aiohttp_response_json_body() -> None:
    resp = _build_aiohttp_response(
        "GET",
        "https://example.com/",
        HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
    )
    assert resp.status == 200


@pytest.mark.anyio
async def test_build_aiohttp_response_text_body() -> None:
    resp = _build_aiohttp_response(
        "GET",
        "https://example.com/",
        HttpResponse(200, body=Body("text", "hello")),
    )
    assert resp.status == 200


@pytest.mark.anyio
async def test_build_aiohttp_response_binary_body() -> None:
    resp = _build_aiohttp_response(
        "GET",
        "https://example.com/",
        HttpResponse(200, body=Body("binary", b"\x00\x01")),
    )
    assert resp.status == 200


@pytest.mark.anyio
async def test_build_aiohttp_response_none_body() -> None:
    resp = _build_aiohttp_response(
        "GET",
        "https://example.com/",
        HttpResponse(200, body=Body("none")),
    )
    assert resp.status == 200
