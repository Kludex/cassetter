from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from vcr_but_better.cassette import Cassette, NoMatchError

if TYPE_CHECKING:
    pass


class VCRTransport(httpx.AsyncBaseTransport):
    """httpx async transport that records/replays via a Cassette."""

    def __init__(self, cassette: Cassette, real_transport: httpx.AsyncBaseTransport) -> None:
        self._cassette = cassette
        self._real_transport = real_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        uri = str(request.url)
        headers = _extract_headers(request.headers)
        body = request.content

        # Try to play from cassette
        try:
            response = self._cassette.play(method, uri, headers, body)
            return _build_httpx_response(response)
        except NoMatchError:
            if not self._cassette.can_record:
                raise

        # Record: make real request
        real_response = await self._real_transport.handle_async_request(request)
        resp_body = real_response.content
        resp_headers = _extract_headers(real_response.headers)

        self._cassette.record(
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
    """httpx sync transport that records/replays via a Cassette."""

    def __init__(self, cassette: Cassette, real_transport: httpx.BaseTransport) -> None:
        self._cassette = cassette
        self._real_transport = real_transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        uri = str(request.url)
        headers = _extract_headers(request.headers)
        body = request.content

        try:
            response = self._cassette.play(method, uri, headers, body)
            return _build_httpx_response(response)
        except NoMatchError:
            if not self._cassette.can_record:
                raise

        real_response = self._real_transport.handle_request(request)
        resp_body = real_response.content
        resp_headers = _extract_headers(real_response.headers)

        self._cassette.record(
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
        self._original_async_transport: httpx.AsyncBaseTransport | None = None
        self._original_sync_transport: httpx.BaseTransport | None = None
        self._patched_async_client: httpx.AsyncClient | None = None
        self._patched_sync_client: httpx.Client | None = None
        self._original_async_init = httpx.AsyncClient.__init__
        self._original_sync_init = httpx.Client.__init__
        self._cassette: Cassette | None = None

    def install(self, cassette: Cassette) -> None:
        self._cassette = cassette
        interceptor = self

        original_async_init = self._original_async_init
        original_sync_init = self._original_sync_init

        def patched_async_init(client_self: httpx.AsyncClient, **kwargs: object) -> None:
            original_async_init(client_self, **kwargs)
            assert interceptor._cassette is not None
            client_self._transport = VCRTransport(interceptor._cassette, client_self._transport)  # type: ignore[assignment]

        def patched_sync_init(client_self: httpx.Client, **kwargs: object) -> None:
            original_sync_init(client_self, **kwargs)
            assert interceptor._cassette is not None
            client_self._transport = VCRSyncTransport(interceptor._cassette, client_self._transport)  # type: ignore[assignment]

        httpx.AsyncClient.__init__ = patched_async_init  # type: ignore[assignment]
        httpx.Client.__init__ = patched_sync_init  # type: ignore[assignment]

    def uninstall(self) -> None:
        httpx.AsyncClient.__init__ = self._original_async_init  # type: ignore[assignment]
        httpx.Client.__init__ = self._original_sync_init  # type: ignore[assignment]
        self._cassette = None


def _extract_headers(headers: httpx.Headers) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        result.setdefault(key.lower(), []).append(value)
    return result


def _build_httpx_response(response: object) -> httpx.Response:
    from vcr_but_better._core import HttpResponse as _HttpResponse

    assert isinstance(response, _HttpResponse)
    headers_list: list[tuple[str, str]] = []
    for key, values in response.headers.items():
        for v in values:
            headers_list.append((key, v))

    body = response.body
    if body.body_type == "json":
        import json

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
    )
