from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import NoMatchError, RawRequest, SkipRecording
from cassetter.intercept._base import InterceptorProtocol

AsyncPassthrough = Callable[[Any], Awaitable[Any]]
SyncPassthrough = Callable[[Any], Any]


async def async_intercept(mod: Any, request: Any, passthrough: AsyncPassthrough) -> Any:
    cassette = get_current_cassette()
    if cassette is None:
        return await passthrough(request)

    method = request.method
    uri = str(request.url)

    if cassette.should_bypass(uri):
        return await passthrough(request)

    headers = extract_headers(request.headers)
    try:
        body: bytes | None = request.content
    except mod.RequestNotRead:
        body = await request.aread()

    hook = cassette.before_record_request
    if hook is not None:
        try:
            raw = hook(RawRequest(method, uri, headers, body))
        except SkipRecording:
            return await passthrough(request)
        method, uri, headers, body = raw.method, raw.uri, raw.headers, raw.body

    try:
        response = cassette.play(method, uri, headers, body)
        return build_response(mod, response, request)
    except NoMatchError:
        if not cassette.can_record:
            raise

    real_response = await passthrough(request)
    await real_response.aread()
    resp_body = real_response.content
    # httpx already decompresses the body, so strip content-encoding
    # to prevent double-decompression in the cassette recorder
    resp_headers = extract_headers_skip_encoding(real_response.headers)

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


def sync_intercept(mod: Any, request: Any, passthrough: SyncPassthrough) -> Any:
    cassette = get_current_cassette()
    if cassette is None:
        return passthrough(request)

    method = request.method
    uri = str(request.url)

    if cassette.should_bypass(uri):
        return passthrough(request)

    headers = extract_headers(request.headers)
    body: bytes | None = request.content

    hook = cassette.before_record_request
    if hook is not None:
        try:
            raw = hook(RawRequest(method, uri, headers, body))
        except SkipRecording:
            return passthrough(request)
        method, uri, headers, body = raw.method, raw.uri, raw.headers, raw.body

    try:
        response = cassette.play(method, uri, headers, body)
        return build_response(mod, response, request)
    except NoMatchError:
        if not cassette.can_record:
            raise

    real_response = passthrough(request)
    real_response.read()
    resp_body = real_response.content
    # httpx already decompresses the body, so strip content-encoding
    resp_headers = extract_headers_skip_encoding(real_response.headers)

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


def extract_headers(headers: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        result.setdefault(key.lower(), []).append(value)
    return result


def extract_headers_skip_encoding(headers: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        lower = key.lower()
        if lower == "content-encoding":
            continue
        result.setdefault(lower, []).append(value)
    return result


def build_response(mod: Any, response: _HttpResponse, request: Any = None) -> Any:
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

    return mod.Response(
        status_code=response.status,
        headers=headers_list,
        content=content,
        request=request,
    )


def make_interceptor(mod: Any) -> type[InterceptorProtocol]:
    """Build an interceptor class bound to an httpx-compatible module (httpx or httpx2)."""

    class VCRAsyncTransport(mod.AsyncBaseTransport):  # type: ignore[misc]
        """Wraps a custom (non-standard) async transport for cassette interception."""

        def __init__(self, real_transport: Any) -> None:
            self._real = real_transport

        async def handle_async_request(self, request: Any) -> Any:
            return await async_intercept(mod, request, lambda r: self._real.handle_async_request(r))

    class VCRSyncTransport(mod.BaseTransport):  # type: ignore[misc]
        """Wraps a custom (non-standard) sync transport for cassette interception."""

        def __init__(self, real_transport: Any) -> None:
            self._real = real_transport

        def handle_request(self, request: Any) -> Any:
            return sync_intercept(mod, request, lambda r: self._real.handle_request(r))

    class Interceptor:
        """Patches the module's transports to record/replay HTTP interactions."""

        def __init__(self) -> None:
            self._original_async_handle = mod.AsyncHTTPTransport.handle_async_request
            self._original_sync_handle = mod.HTTPTransport.handle_request
            self._original_async_init = mod.AsyncClient.__init__
            self._original_sync_init = mod.Client.__init__

        def install(self) -> None:
            original_async_handle = self._original_async_handle
            original_sync_handle = self._original_sync_handle
            original_async_init = self._original_async_init
            original_sync_init = self._original_sync_init

            # Patch transport classes to intercept pre-existing clients
            async def patched_async_handle(transport_self: Any, request: Any) -> Any:
                return await async_intercept(mod, request, lambda r: original_async_handle(transport_self, r))

            def patched_sync_handle(transport_self: Any, request: Any) -> Any:
                return sync_intercept(mod, request, lambda r: original_sync_handle(transport_self, r))

            mod.AsyncHTTPTransport.handle_async_request = patched_async_handle
            mod.HTTPTransport.handle_request = patched_sync_handle

            # Patch __init__ to wrap custom (non-standard) transports
            def patched_async_init(client_self: Any, **kwargs: Any) -> None:
                original_async_init(client_self, **kwargs)
                if not isinstance(client_self._transport, mod.AsyncHTTPTransport):
                    client_self._transport = VCRAsyncTransport(client_self._transport)

            def patched_sync_init(client_self: Any, **kwargs: Any) -> None:
                original_sync_init(client_self, **kwargs)
                if not isinstance(client_self._transport, mod.HTTPTransport):
                    client_self._transport = VCRSyncTransport(client_self._transport)

            mod.AsyncClient.__init__ = patched_async_init
            mod.Client.__init__ = patched_sync_init

        def uninstall(self) -> None:
            mod.AsyncHTTPTransport.handle_async_request = self._original_async_handle
            mod.HTTPTransport.handle_request = self._original_sync_handle
            mod.AsyncClient.__init__ = self._original_async_init
            mod.Client.__init__ = self._original_sync_init

    return Interceptor
