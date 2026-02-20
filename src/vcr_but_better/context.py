from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from vcr_but_better._core import MatchConfig, SecurityConfig
from vcr_but_better.cassette import Cassette
from vcr_but_better.intercept._base import InterceptorProtocol
from vcr_but_better.intercept._httpx import HttpxInterceptor
from vcr_but_better.recording import RecordMode

try:
    from vcr_but_better.intercept._aiohttp import AiohttpInterceptor
except ImportError:  # pragma: no cover
    AiohttpInterceptor = None  # type: ignore[assignment, misc]

try:
    from vcr_but_better.intercept._requests import RequestsInterceptor
except ImportError:  # pragma: no cover
    RequestsInterceptor = None  # type: ignore[assignment, misc]

try:
    from vcr_but_better.intercept._grpc import GrpcInterceptor
except ImportError:  # pragma: no cover
    GrpcInterceptor = None  # type: ignore[assignment, misc]

try:
    from vcr_but_better.intercept._websockets import WebSocketInterceptor
except ImportError:  # pragma: no cover
    WebSocketInterceptor = None  # type: ignore[assignment, misc]

_INTERCEPTOR_MAP: dict[str, type[InterceptorProtocol] | None] = {
    "httpx": HttpxInterceptor,
    "aiohttp": AiohttpInterceptor,
    "requests": RequestsInterceptor,
    "grpc": GrpcInterceptor,
    "websockets": WebSocketInterceptor,
}


@contextlib.asynccontextmanager
async def use_cassette(
    path: str,
    *,
    record_mode: RecordMode | str = RecordMode.ONCE,
    match_on: list[str] | None = None,
    ignore_json_paths: list[str] | None = None,
    filtered_headers: list[str] | None = None,
    filtered_query_params: list[str] | None = None,
    body_scrub_patterns: list[str] | None = None,
    filter_replacement: str | None = None,
    intercept: list[str] | None = None,
) -> AsyncIterator[Cassette]:
    """Async context manager for recording/replaying HTTP interactions.

    Args:
        path: Path to the cassette YAML file.
        record_mode: Controls recording behavior.
        match_on: Fields to match on (default: ["method", "uri"]).
        ignore_json_paths: JSON paths to ignore during matching.
        filtered_headers: Headers to filter from cassettes.
        filtered_query_params: Query params to filter.
        body_scrub_patterns: Body patterns to scrub.
        filter_replacement: Replacement string for filtered values.
        intercept: HTTP libraries to intercept (default: auto-detect).
    """
    if isinstance(record_mode, str):
        record_mode = RecordMode.from_str(record_mode)

    match_config = MatchConfig(match_on=match_on, ignore_json_paths=ignore_json_paths)

    security_kwargs: dict[str, Any] = {}
    if filtered_headers is not None:
        security_kwargs["filtered_headers"] = filtered_headers
    if filtered_query_params is not None:
        security_kwargs["filtered_query_params"] = filtered_query_params
    if body_scrub_patterns is not None:
        security_kwargs["body_scrub_patterns"] = body_scrub_patterns
    if filter_replacement is not None:
        security_kwargs["replacement"] = filter_replacement
    security_config = SecurityConfig(**security_kwargs)

    cassette = Cassette(
        path,
        record_mode=record_mode,
        match_config=match_config,
        security_config=security_config,
    )
    cassette.load()

    interceptors = resolve_interceptors(intercept or ["httpx"])

    for interceptor in interceptors:
        interceptor.install(cassette)

    try:
        yield cassette
    finally:
        for interceptor in reversed(interceptors):
            interceptor.uninstall()
        cassette.save()


def resolve_interceptors(names: list[str]) -> list[InterceptorProtocol]:
    """Import and instantiate interceptors by name."""
    interceptors: list[InterceptorProtocol] = []
    for name in names:
        cls = _INTERCEPTOR_MAP.get(name)
        if cls is None:
            if name in _INTERCEPTOR_MAP:
                raise ImportError(f"interceptor {name!r} requires installing the '{name}' extra")
            raise ValueError(f"unknown interceptor: {name!r}")
        interceptors.append(cls())
    return interceptors
