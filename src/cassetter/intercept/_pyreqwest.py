from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable
from typing import Any

from pyreqwest.middleware import Next, SyncNext
from pyreqwest.request import (
    ConsumedRequest,
    OneOffRequestBuilder,
    Request,
    RequestBody,
    RequestBuilder,
    StreamRequest,
    SyncConsumedRequest,
    SyncOneOffRequestBuilder,
    SyncRequestBuilder,
    SyncStreamRequest,
)
from pyreqwest.response import BaseResponse, Response, ResponseBuilder, SyncResponse

from cassetter._core import HttpResponse as _HttpResponse
from cassetter._state import get_current_cassette
from cassetter.cassette import Cassette, NoMatchError, RawRequest
from cassetter.compare import body_to_bytes
from cassetter.intercept._shared import apply_before_record_request, extract_headers

INTERCEPTED = "cassetter.intercepted"


class PyreqwestInterceptor:
    """Intercepts pyreqwest by adding a middleware to every request it builds."""

    def __init__(self) -> None:
        self._originals: list[tuple[type[Any], str, Any]] = []

    def install(self) -> None:
        patches: list[tuple[type[Any], str, Callable[[Any], Any]]] = [
            (RequestBuilder, "build", build_with(async_middleware)),
            (RequestBuilder, "build_streamed", build_with(async_middleware)),
            (SyncRequestBuilder, "build", build_with(sync_middleware)),
            (SyncRequestBuilder, "build_streamed", build_with(sync_middleware)),
            (OneOffRequestBuilder, "send", send_with(async_middleware)),
            (SyncOneOffRequestBuilder, "send", send_with(sync_middleware)),
            (ConsumedRequest, "send", require_intercepted),
            (SyncConsumedRequest, "send", require_intercepted),
            (StreamRequest, "__aenter__", require_intercepted),
            (SyncStreamRequest, "__enter__", require_intercepted),
        ]
        for cls, name, wrap in patches:
            original = getattr(cls, name)
            self._originals.append((cls, name, original))
            setattr(cls, name, wrap(original))

    def uninstall(self) -> None:
        for cls, name, original in reversed(self._originals):
            setattr(cls, name, original)
        self._originals.clear()


def build_with(middleware: Any) -> Callable[[Any], Any]:
    def wrap(original: Callable[[Any], Request]) -> Callable[[Any], Request]:
        def build(builder: Any) -> Request:
            request = original(builder.with_middleware(middleware))
            request.extensions = {**request.extensions, INTERCEPTED: True}
            return request

        return build

    return wrap


def send_with(middleware: Any) -> Callable[[Any], Any]:
    return lambda original: lambda builder: original(builder.with_middleware(middleware))


def require_intercepted(original: Callable[[Request], Any]) -> Callable[[Request], Any]:
    """Refuse to send a request built before the cassette was entered, since it has no middleware to replay it."""

    def send(request: Request) -> Any:
        cassette = get_current_cassette()
        if (
            cassette is not None
            and INTERCEPTED not in request.extensions
            and not cassette.should_bypass(str(request.url))
        ):
            raise RuntimeError(
                f"{request.method} {request.url} was built before the cassette was entered, so it cannot be "
                "recorded or replayed. Build pyreqwest requests inside the cassette."
            )
        return original(request)

    return send


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
