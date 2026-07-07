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

# Active cassettes entered via use_cassette or the pytest plugin, in entry
# order. Threads spawned by libraries that don't propagate contextvars (e.g.
# Temporal/DBOS worker threads) have an empty context, so they fall back to
# the most recently entered active cassette.
_fallback_cassettes: list[Cassette] = []


def get_current_cassette() -> Cassette | None:
    cassette = current_cassette.get()
    if cassette is not None:
        return cassette
    with lock:
        return _fallback_cassettes[-1] if _fallback_cassettes else None


def push_fallback_cassette(cassette: Cassette) -> None:
    with lock:
        _fallback_cassettes.append(cassette)


def pop_fallback_cassette(cassette: Cassette) -> None:
    with lock:
        # Remove by identity so out-of-order exits of concurrent cassettes
        # never clobber one another.
        for i in range(len(_fallback_cassettes) - 1, -1, -1):
            if _fallback_cassettes[i] is cassette:
                del _fallback_cassettes[i]
                break


def acquire_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with lock:
        acquired: list[type[InterceptorProtocol]] = []
        try:
            for cls in interceptor_classes:
                if cls in installed:
                    instance, count = installed[cls]
                    installed[cls] = (instance, count + 1)
                else:
                    instance = cls()
                    instance.install()
                    installed[cls] = (instance, 1)
                acquired.append(cls)
        except BaseException:
            # Roll back so a failed install never leaves earlier patches
            # applied with no owner to release them.
            _release_locked(acquired)
            raise


def _release_locked(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    for cls in interceptor_classes:
        if cls not in installed:  # pragma: no cover - defensive: release of an unheld interceptor
            continue
        instance, count = installed[cls]
        if count <= 1:
            instance.uninstall()
            del installed[cls]
        else:
            installed[cls] = (instance, count - 1)


def release_patches(interceptor_classes: list[type[InterceptorProtocol]]) -> None:
    with lock:
        _release_locked(interceptor_classes)
