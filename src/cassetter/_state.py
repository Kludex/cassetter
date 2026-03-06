from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cassetter.cassette import Cassette
    from cassetter.intercept._base import InterceptorProtocol

_current_cassette: ContextVar[Cassette | None] = ContextVar("_current_cassette", default=None)

_lock = threading.Lock()
_installed: dict[type, tuple[InterceptorProtocol, int]] = {}


def get_current_cassette() -> Cassette | None:
    return _current_cassette.get()


def acquire_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with _lock:
        for cls in interceptor_classes:
            if cls in _installed:
                instance, count = _installed[cls]
                _installed[cls] = (instance, count + 1)
            else:
                instance = cls()
                instance.install()
                _installed[cls] = (instance, 1)


def release_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with _lock:
        for cls in interceptor_classes:
            if cls not in _installed:
                continue
            instance, count = _installed[cls]
            if count <= 1:
                instance.uninstall()
                del _installed[cls]
            else:
                _installed[cls] = (instance, count - 1)
