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


class TestAiohttpInterceptor:
    @pytest.mark.anyio
    async def test_replay(self, tmp_path: object) -> None:
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
    async def test_no_match_cant_record(self, tmp_path: object) -> None:
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
    async def test_record(self, tmp_path: object) -> None:
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

    def test_install_uninstall(self) -> None:
        interceptor = AiohttpInterceptor()
        original_request = aiohttp.ClientSession._request
        cassette = Cassette("/nonexistent", record_mode=RecordMode.NONE)
        cassette.load()

        interceptor.install(cassette)
        assert aiohttp.ClientSession._request is not original_request

        interceptor.uninstall()
        assert aiohttp.ClientSession._request is original_request


class TestExtractRequestHeaders:
    def test_dict_headers(self) -> None:
        headers = _extract_request_headers({"Content-Type": "application/json", "Accept": "text/html"})
        assert headers == {"content-type": ["application/json"], "accept": ["text/html"]}

    def test_none_headers(self) -> None:
        assert _extract_request_headers(None) == {}


class TestExtractRequestBody:
    def test_bytes_data(self) -> None:
        assert _extract_request_body({"data": b"hello"}) == b"hello"

    def test_str_data(self) -> None:
        assert _extract_request_body({"data": "hello"}) == b"hello"

    def test_json_data(self) -> None:
        result = _extract_request_body({"json": {"key": "value"}})
        assert result is not None
        assert b"key" in result

    def test_no_body(self) -> None:
        assert _extract_request_body({}) is None

    def test_none_data(self) -> None:
        assert _extract_request_body({"data": None}) is None


class TestExtractResponseHeaders:
    def test_multidict_headers(self) -> None:
        from multidict import CIMultiDict, CIMultiDictProxy

        headers = CIMultiDictProxy(CIMultiDict([("Content-Type", "application/json"), ("X-Custom", "value")]))
        result = _extract_response_headers(headers)
        assert result == {"content-type": ["application/json"], "x-custom": ["value"]}


class TestBuildAiohttpResponse:
    @pytest.mark.anyio
    async def test_json_body(self) -> None:
        resp = _build_aiohttp_response(
            "GET",
            "https://example.com/",
            HttpResponse(200, {"content-type": ["application/json"]}, Body("json", {"key": "value"})),
        )
        assert resp.status == 200

    @pytest.mark.anyio
    async def test_text_body(self) -> None:
        resp = _build_aiohttp_response(
            "GET",
            "https://example.com/",
            HttpResponse(200, body=Body("text", "hello")),
        )
        assert resp.status == 200

    @pytest.mark.anyio
    async def test_binary_body(self) -> None:
        resp = _build_aiohttp_response(
            "GET",
            "https://example.com/",
            HttpResponse(200, body=Body("binary", b"\x00\x01")),
        )
        assert resp.status == 200

    @pytest.mark.anyio
    async def test_none_body(self) -> None:
        resp = _build_aiohttp_response(
            "GET",
            "https://example.com/",
            HttpResponse(200, body=Body("none")),
        )
        assert resp.status == 200
