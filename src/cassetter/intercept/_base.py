from __future__ import annotations

from urllib.parse import urlparse

from typing_extensions import Protocol

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def is_localhost(uri: str) -> bool:
    host = urlparse(uri).hostname or ""
    return host in _LOCALHOST_HOSTS


class InterceptorProtocol(Protocol):
    """Protocol that all interceptors must satisfy."""

    def install(self) -> None: ...
    def uninstall(self) -> None: ...
