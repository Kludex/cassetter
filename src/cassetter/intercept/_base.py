from __future__ import annotations

from urllib.parse import urlparse

from typing_extensions import Protocol

from cassetter.cassette import Cassette

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def is_localhost(uri: str) -> bool:
    host = urlparse(uri).hostname or ""
    return host in _LOCALHOST_HOSTS


class InterceptorProtocol(Protocol):
    """Protocol that all interceptors must satisfy."""

    def install(self, cassette: Cassette) -> None: ...
    def uninstall(self) -> None: ...
