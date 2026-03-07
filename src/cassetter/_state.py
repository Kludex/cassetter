from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cassetter.cassette import Cassette
    from cassetter.intercept._base import InterceptorProtocol

current_cassette: ContextVar[Cassette | None] = ContextVar("current_cassette", default=None)

lock = threading.Lock()
installed: dict[type, tuple[InterceptorProtocol, int]] = {}


def get_current_cassette() -> Cassette | None:
    return current_cassette.get()


def acquire_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with lock:
        for cls in interceptor_classes:
            if cls in installed:
                instance, count = installed[cls]
                installed[cls] = (instance, count + 1)
            else:
                instance = cls()
                instance.install()
                installed[cls] = (instance, 1)


def release_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with lock:
        for cls in interceptor_classes:
            if cls not in installed:
                continue
            instance, count = installed[cls]
            if count <= 1:
                instance.uninstall()
                del installed[cls]
            else:
                installed[cls] = (instance, count - 1)
