from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from cassetter._core import MatchConfig, SecurityConfig
from cassetter._state import _current_cassette, acquire_patches, release_patches
from cassetter.cassette import BeforeRecordRequest, Cassette
from cassetter.intercept._base import InterceptorProtocol
from cassetter.intercept._httpx import HttpxInterceptor
from cassetter.recording import RecordMode

try:
    from cassetter.intercept._aiohttp import AiohttpInterceptor
except ImportError:  # pragma: no cover
    AiohttpInterceptor = None  # type: ignore[assignment, misc]

try:
    from cassetter.intercept._requests import RequestsInterceptor
except ImportError:  # pragma: no cover
    RequestsInterceptor = None  # type: ignore[assignment, misc]

try:
    from cassetter.intercept._grpc import GrpcInterceptor
except ImportError:  # pragma: no cover
    GrpcInterceptor = None  # type: ignore[assignment, misc]

try:
    from cassetter.intercept._websockets import WebSocketInterceptor
except ImportError:  # pragma: no cover
    WebSocketInterceptor = None  # type: ignore[assignment, misc]

try:
    from cassetter.intercept._urllib3 import Urllib3Interceptor
except ImportError:  # pragma: no cover
    Urllib3Interceptor = None  # type: ignore[assignment, misc]

try:
    from cassetter.intercept._pyreqwest import PyreqwestInterceptor
except ImportError:  # pragma: no cover
    PyreqwestInterceptor = None  # type: ignore[assignment, misc]

_INTERCEPTOR_MAP: dict[str, type[InterceptorProtocol] | None] = {
    "httpx": HttpxInterceptor,
    "aiohttp": AiohttpInterceptor,
    "requests": RequestsInterceptor,
    "grpc": GrpcInterceptor,
    "websockets": WebSocketInterceptor,
    "urllib3": Urllib3Interceptor,
    "pyreqwest": PyreqwestInterceptor,
}

# Interceptors to enable by default, in order. urllib3 subsumes requests,
# so requests is excluded when urllib3 is available.
_AUTO_DETECT_ORDER: list[str] = ["httpx", "urllib3", "aiohttp"]
_SUBSUMED_BY: dict[str, str] = {"requests": "urllib3"}


@contextlib.contextmanager
def use_cassette(
    path: str | os.PathLike[str],
    *,
    record_mode: RecordMode | str = RecordMode.ONCE,
    match_on: list[str] | None = None,
    ignore_json_paths: list[str] | None = None,
    filter_headers: list[str] | None = None,
    filter_query_params: list[str] | None = None,
    body_scrub_patterns: list[str] | None = None,
    filter_replacement: str | None = None,
    intercept: list[str] | None = None,
    max_age: str | None = None,
    on_expiry: str = "warn",
    ignore_localhost: bool = False,
    ignore_hosts: list[str] | None = None,
    before_record_request: BeforeRecordRequest | None = None,
) -> Iterator[Cassette]:
    """Context manager for recording/replaying HTTP interactions.

    Args:
        path: Path to the cassette YAML file.
        record_mode: Controls recording behavior.
        match_on: Fields to match on (default: ["method", "uri"]).
        ignore_json_paths: JSON paths to ignore during matching.
        filter_headers: Headers to filter from cassettes.
        filter_query_params: Query params to filter.
        body_scrub_patterns: Body patterns to scrub.
        filter_replacement: Replacement string for filtered values.
        intercept: HTTP libraries to intercept (default: auto-detect).
    """
    if isinstance(record_mode, str):
        record_mode = RecordMode.from_str(record_mode)

    match_config = MatchConfig(match_on=match_on, ignore_json_paths=ignore_json_paths)

    security_kwargs: dict[str, Any] = {}
    if filter_headers is not None:
        security_kwargs["filter_headers"] = filter_headers
    if filter_query_params is not None:
        security_kwargs["filter_query_params"] = filter_query_params
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
        max_age=max_age,
        on_expiry=on_expiry,
        ignore_localhost=ignore_localhost,
        ignore_hosts=ignore_hosts,
        before_record_request=before_record_request,
    )
    cassette.load()

    interceptor_classes = resolve_interceptors(intercept)

    acquire_patches(interceptor_classes)
    token = _current_cassette.set(cassette)

    try:
        yield cassette
    finally:
        _current_cassette.reset(token)
        release_patches(interceptor_classes)
        cassette.save()


def resolve_interceptors(names: list[str] | None = None) -> list[type[InterceptorProtocol]]:
    """Import and return interceptor classes by name, or auto-detect if None."""
    if names is None:
        return _auto_detect_interceptors()
    interceptors: list[type[InterceptorProtocol]] = []
    for name in names:
        cls = _INTERCEPTOR_MAP.get(name)
        if cls is None:
            if name in _INTERCEPTOR_MAP:
                raise ImportError(f"interceptor {name!r} requires installing the '{name}' extra")
            raise ValueError(f"unknown interceptor: {name!r}")
        interceptors.append(cls)
    return interceptors


def _auto_detect_interceptors() -> list[type[InterceptorProtocol]]:
    """Detect installed HTTP libraries and return interceptor classes for all of them."""
    available: list[str] = []
    for name in _AUTO_DETECT_ORDER:
        if _INTERCEPTOR_MAP.get(name) is not None:
            available.append(name)
    if not available:
        raise ImportError("no HTTP interceptors available - install httpx, urllib3, or aiohttp")
    return [_INTERCEPTOR_MAP[name] for name in available]  # type: ignore[misc]
