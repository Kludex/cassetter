from __future__ import annotations

from cassetter.intercept._base import InterceptorProtocol

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
