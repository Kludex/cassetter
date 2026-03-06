from __future__ import annotations

import json
from typing import Any

import httpx

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import BypassCassette, NoMatchError, RawRequest


class VCRTransport(httpx.AsyncBaseTransport):
    """httpx async transport that records/replays via the current context's Cassette."""

    def __init__(self, real_transport: httpx.AsyncBaseTransport) -> None:
        self._real_transport = real_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        cassette = get_current_cassette()
        if cassette is None:
            return await self._real_transport.handle_async_request(request)

        method = request.method
        uri = str(request.url)

        if cassette.should_bypass(uri):
            return await self._real_transport.handle_async_request(request)

        headers = _extract_headers(request.headers)
        try:
            body = request.content
        except httpx.RequestNotRead:
            body = await request.aread()

        hook = cassette.before_record_request
        if hook is not None:
            try:
                hook(RawRequest(method, uri, headers, body))
            except BypassCassette:
                return await self._real_transport.handle_async_request(request)

        try:
            response = cassette.play(method, uri, headers, body)
            return _build_httpx_response(response, request)
        except NoMatchError:
            if not cassette.can_record:
                raise

        real_response = await self._real_transport.handle_async_request(request)
        await real_response.aread()
        resp_body = real_response.content
        # httpx already decompresses the body, so strip content-encoding
        # to prevent double-decompression in the cassette recorder
        resp_headers = _extract_headers_skip_encoding(real_response.headers)

        cassette.record(
            method=method,
            uri=uri,
            request_headers=headers,
            request_body=body,
            status=real_response.status_code,
            response_headers=resp_headers,
            response_body=resp_body,
        )
        return real_response


class VCRSyncTransport(httpx.BaseTransport):
    """httpx sync transport that records/replays via the current context's Cassette."""

    def __init__(self, real_transport: httpx.BaseTransport) -> None:
        self._real_transport = real_transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        cassette = get_current_cassette()
        if cassette is None:
            return self._real_transport.handle_request(request)

        method = request.method
        uri = str(request.url)

        if cassette.should_bypass(uri):
            return self._real_transport.handle_request(request)

        headers = _extract_headers(request.headers)
        body = request.content

        hook = cassette.before_record_request
        if hook is not None:
            try:
                hook(RawRequest(method, uri, headers, body))
            except BypassCassette:
                return self._real_transport.handle_request(request)

        try:
            response = cassette.play(method, uri, headers, body)
            return _build_httpx_response(response, request)
        except NoMatchError:
            if not cassette.can_record:
                raise

        real_response = self._real_transport.handle_request(request)
        real_response.read()
        resp_body = real_response.content
        # httpx already decompresses the body, so strip content-encoding
        resp_headers = _extract_headers_skip_encoding(real_response.headers)

        cassette.record(
            method=method,
            uri=uri,
            request_headers=headers,
            request_body=body,
            status=real_response.status_code,
            response_headers=resp_headers,
            response_body=resp_body,
        )
        return real_response


class HttpxInterceptor:
    """Installs VCR transports on the default httpx client."""

    def __init__(self) -> None:
        self._original_async_init = httpx.AsyncClient.__init__
        self._original_sync_init = httpx.Client.__init__

    def install(self) -> None:
        original_async_init = self._original_async_init
        original_sync_init = self._original_sync_init

        def patched_async_init(client_self: httpx.AsyncClient, **kwargs: Any) -> None:
            original_async_init(client_self, **kwargs)
            client_self._transport = VCRTransport(client_self._transport)

        def patched_sync_init(client_self: httpx.Client, **kwargs: Any) -> None:
            original_sync_init(client_self, **kwargs)
            client_self._transport = VCRSyncTransport(client_self._transport)

        httpx.AsyncClient.__init__ = patched_async_init  # type: ignore[assignment,method-assign]
        httpx.Client.__init__ = patched_sync_init  # type: ignore[assignment,method-assign]

    def uninstall(self) -> None:
        httpx.AsyncClient.__init__ = self._original_async_init  # type: ignore[method-assign]
        httpx.Client.__init__ = self._original_sync_init  # type: ignore[method-assign]


def _extract_headers(headers: httpx.Headers) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        result.setdefault(key.lower(), []).append(value)
    return result


def _extract_headers_skip_encoding(headers: httpx.Headers) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        lower = key.lower()
        if lower == "content-encoding":
            continue
        result.setdefault(lower, []).append(value)
    return result


def _build_httpx_response(response: _HttpResponse, request: httpx.Request | None = None) -> httpx.Response:
    headers_list: list[tuple[str, str]] = []
    for key, values in response.headers.items():
        for v in values:
            headers_list.append((key, v))

    body = response.body
    if body.body_type == "json":
        content = json.dumps(body.content).encode()
    elif body.body_type == "text":
        content = body.content.encode() if isinstance(body.content, str) else b""
    elif body.body_type == "binary":
        content = body.content if isinstance(body.content, bytes) else b""
    else:
        content = b""

    return httpx.Response(
        status_code=response.status,
        headers=headers_list,
        content=content,
        request=request,
    )
