from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable
from typing import Any

from pyreqwest.middleware import Next, SyncNext
from pyreqwest.request import (
    OneOffRequestBuilder,
    Request,
    RequestBody,
    RequestBuilder,
    SyncOneOffRequestBuilder,
    SyncRequestBuilder,
)
from pyreqwest.response import BaseResponse, Response, ResponseBuilder, SyncResponse

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import Cassette, NoMatchError, RawRequest
from cassetter.compare import body_to_bytes
from cassetter.intercept._shared import apply_before_record_request, extract_headers


class PyreqwestInterceptor:
    """Intercepts pyreqwest by adding a middleware to every request it builds."""

    def __init__(self) -> None:
        self._originals: list[tuple[type[Any], str, Any]] = []

    def install(self) -> None:
        patches: list[tuple[type[Any], str, Any]] = [
            (RequestBuilder, "build", async_middleware),
            (RequestBuilder, "build_streamed", async_middleware),
            (SyncRequestBuilder, "build", sync_middleware),
            (SyncRequestBuilder, "build_streamed", sync_middleware),
            (OneOffRequestBuilder, "send", async_middleware),
            (SyncOneOffRequestBuilder, "send", sync_middleware),
        ]
        for cls, name, middleware in patches:
            original = getattr(cls, name)
            self._originals.append((cls, name, original))
            setattr(cls, name, with_middleware(original, middleware))

    def uninstall(self) -> None:
        for cls, name, original in reversed(self._originals):
            setattr(cls, name, original)
        self._originals.clear()


def with_middleware(original: Callable[[Any], Any], middleware: Any) -> Callable[[Any], Any]:
    return lambda builder: original(builder.with_middleware(middleware))


async def async_middleware(request: Request, next_handler: Next) -> Response:
    cassette = get_current_cassette()
    if cassette is None or cassette.should_bypass(str(request.url)):
        return await next_handler.run(request)

    if request.body is not None and isinstance(stream := request.body.get_stream(), AsyncIterable):
        body = b"".join([bytes(chunk) async for chunk in stream])
        request = request.from_request_and_body(request, RequestBody.from_bytes(body))

    raw = apply_before_record_request(cassette, *describe(request))
    if raw is None:
        return await next_handler.run(request)
    replay, expected = lookup(cassette, raw)
    if replay is not None:
        return await replay.build()

    order = cassette.reserve_record_order()
    response = await next_handler.run(request)
    record(cassette, raw, response, (await response.bytes()).to_bytes(), order, expected)
    return response


def sync_middleware(request: Request, next_handler: SyncNext) -> SyncResponse:
    cassette = get_current_cassette()
    if cassette is None or cassette.should_bypass(str(request.url)):
        return next_handler.run(request)

    if request.body is not None and isinstance(stream := request.body.get_stream(), Iterable):
        body = b"".join(bytes(chunk) for chunk in stream)
        request = request.from_request_and_body(request, RequestBody.from_bytes(body))

    raw = apply_before_record_request(cassette, *describe(request))
    if raw is None:
        return next_handler.run(request)
    replay, expected = lookup(cassette, raw)
    if replay is not None:
        return replay.build_sync()

    order = cassette.reserve_record_order()
    response = next_handler.run(request)
    record(cassette, raw, response, response.bytes().to_bytes(), order, expected)
    return response


def describe(request: Request) -> tuple[str, str, dict[str, list[str]], bytes | None]:
    body = request.body.copy_bytes() if request.body is not None else None
    return (
        request.method,
        str(request.url),
        extract_headers(request.headers.items()),
        body.to_bytes() if body is not None else None,
    )


def lookup(cassette: Cassette, raw: RawRequest) -> tuple[ResponseBuilder | None, tuple[int, _HttpResponse] | None]:
    """Return a builder for the recorded response, or the `verify` expectation to compare a live call against."""
    try:
        expected = cassette.match(raw.method, raw.uri, raw.headers, raw.body)
    except NoMatchError:
        if not cassette.can_record:
            raise
        return None, None
    if cassette.verifies:
        return None, expected
    response = expected[1]
    headers = [(name, value) for name, values in response.headers.items() for value in values]
    return ResponseBuilder().status(response.status).headers(headers).body_bytes(body_to_bytes(response.body)), None


def record(
    cassette: Cassette,
    raw: RawRequest,
    response: BaseResponse,
    body: bytes,
    order: int,
    expected: tuple[int, _HttpResponse] | None,
) -> None:
    cassette.record(
        method=raw.method,
        uri=raw.uri,
        request_headers=raw.headers,
        request_body=raw.body,
        status=response.status,
        response_headers=extract_headers(response.headers.items()),
        response_body=body,
        order=order,
        expected=expected,
    )
