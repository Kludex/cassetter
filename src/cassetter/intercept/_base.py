from __future__ import annotations

from typing_extensions import Protocol

from cassetter.cassette import Cassette


class InterceptorProtocol(Protocol):
    """Protocol that all interceptors must satisfy."""

    def install(self, cassette: Cassette) -> None: ...
    def uninstall(self) -> None: ...
