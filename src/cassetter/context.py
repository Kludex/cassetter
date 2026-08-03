from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from cassetter._core import MatchConfig, SecurityConfig
from cassetter._state import acquire_patches, current_cassette, release_patches
from cassetter.cassette import BeforeRecordRequest, BeforeRecordResponse, Cassette
from cassetter.intercept._base import InterceptorProtocol
from cassetter.recording import RecordMode

if TYPE_CHECKING:
    from cassetter._core import Matcher

try:
    from cassetter.intercept._httpx import HttpxInterceptor
except ImportError:  # pragma: no cover
    HttpxInterceptor = None  # type: ignore[assignment]

try:
    from cassetter.intercept._httpx2 import Httpx2Interceptor
except ImportError:  # pragma: no cover
    Httpx2Interceptor = None  # type: ignore[assignment]

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
    "httpx2": Httpx2Interceptor,
    "aiohttp": AiohttpInterceptor,
    "requests": RequestsInterceptor,
    "grpc": GrpcInterceptor,
    "websockets": WebSocketInterceptor,
    "urllib3": Urllib3Interceptor,
    "pyreqwest": PyreqwestInterceptor,
}

# Interceptors auto-detected by default, in order. requests is intentionally
# omitted: requests traffic flows through urllib3, so recording both layers
# would capture each request twice. Callers who want requests can name it
# explicitly.
_AUTO_DETECT_ORDER: list[str] = ["httpx", "httpx2", "urllib3", "aiohttp"]


@contextlib.contextmanager
def use_cassette(
    path: str | os.PathLike[str],
    *,
    record_mode: RecordMode | str = RecordMode.ONCE,
    match_on: list[Matcher] | None = None,
    ignore_json_paths: list[str] | None = None,
    filter_headers: list[str] | None = None,
    filter_query_parameters: list[str] | None = None,
    body_scrub_patterns: list[str] | None = None,
    filter_replacement: str | None = None,
    intercept: list[str] | None = None,
    max_age: str | None = None,
    on_expiry: str = "warn",
    ignore_localhost: bool = False,
    ignore_hosts: list[str] | None = None,
    before_record_request: BeforeRecordRequest | None = None,
    before_record_response: BeforeRecordResponse | None = None,
) -> Iterator[Cassette]:
    """Context manager for recording/replaying HTTP interactions.

    Args:
        path: Path to the cassette YAML file.
        record_mode: Controls recording behavior.
        match_on: Fields to match on (default: ["method", "uri"]).
        ignore_json_paths: JSON paths to ignore during matching.
        filter_headers: Headers to filter from cassettes.
        filter_query_parameters: Query params to filter.
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
    if filter_query_parameters is not None:
        security_kwargs["filter_query_parameters"] = filter_query_parameters
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
        before_record_response=before_record_response,
    )
    cassette.load()

    interceptor_classes = resolve_interceptors(intercept)

    acquire_patches(interceptor_classes)
    token = current_cassette.set(cassette)

    try:
        yield cassette
    finally:
        current_cassette.reset(token)
        release_patches(interceptor_classes)
        cassette.save()


def resolve_interceptors(names: list[str] | None = None) -> list[type[InterceptorProtocol]]:
    """Import and return interceptor classes by name, or auto-detect if None."""
    if names is None:
        return _auto_detect_interceptors()
    # An explicit list installs exactly what was requested. requests and
    # urllib3 overlap (requests flows through urllib3), but a session with a
    # custom adapter may not, so dropping a requested interceptor could
    # silently bypass the cassette. Auto-detect avoids the overlap instead.
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
        raise ImportError("no HTTP interceptors available - install httpx, httpx2, urllib3, or aiohttp")
    return [_INTERCEPTOR_MAP[name] for name in available]  # type: ignore[misc]
