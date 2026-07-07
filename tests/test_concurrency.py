"""Concurrency tests for cassetter.

Verifies that multiple cassettes can run concurrently without cross-contamination,
both in async tasks and across threads (ThreadPoolExecutor).
Inspired by govcr's concurrency_test.go which runs 50 goroutines simultaneously.
"""

from __future__ import annotations

import contextvars
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import anyio
import httpx
import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter._state import acquire_patches, current_cassette, release_patches
from cassetter.cassette import Cassette, NoMatchError
from cassetter.context import use_cassette
from cassetter.intercept._httpx import HttpxInterceptor
from cassetter.recording import RecordMode

pytest_plugins = ("anyio",)


async def _gather(*async_fns: Any) -> list[Any]:
    """Run async callables concurrently and return results (anyio-compatible)."""
    results: list[Any] = [None] * len(async_fns)

    async def _run(index: int, fn: Any) -> None:
        results[index] = await fn()

    async with anyio.create_task_group() as tg:
        for i, fn in enumerate(async_fns):
            tg.start_soon(_run, i, fn)

    return results


def _make_cassette(path: str, url: str, response_data: dict[str, object]) -> str:
    """Create a cassette file with a single GET interaction."""
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", url),
            response=HttpResponse(200, {"content-type": ["application/json"]}, Body("json", response_data)),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    return path


# ---------------------------------------------------------------------------
# Async concurrency
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_two_concurrent_async_cassettes(tmp_path: object) -> None:
    """Two async tasks using different cassettes concurrently get correct responses."""
    dir_path = str(tmp_path)
    path_a = _make_cassette(os.path.join(dir_path, "a.yaml"), "https://api.example.com/data", {"source": "a"})
    path_b = _make_cassette(os.path.join(dir_path, "b.yaml"), "https://api.example.com/data", {"source": "b"})

    async def task_a() -> dict[str, object]:
        with use_cassette(path_a, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    async def task_b() -> dict[str, object]:
        with use_cassette(path_b, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    result_a, result_b = await _gather(task_a, task_b)

    assert result_a == {"source": "a"}
    assert result_b == {"source": "b"}


@pytest.mark.anyio
async def test_many_concurrent_async_cassettes(tmp_path: object) -> None:
    """N concurrent async tasks each get their own cassette - like Go's 50 goroutine test."""
    dir_path = str(tmp_path)
    n = 50

    paths = []
    for i in range(n):
        path = _make_cassette(
            os.path.join(dir_path, f"cassette_{i}.yaml"),
            "https://api.example.com/data",
            {"index": i},
        )
        paths.append(path)

    async def worker(index: int) -> dict[str, object]:
        with use_cassette(paths[index], record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    results = await _gather(*[lambda i=i: worker(i) for i in range(n)])

    for i, result in enumerate(results):
        assert result == {"index": i}, f"task {i} got wrong cassette: {result}"


@pytest.mark.anyio
async def test_nested_cassettes(tmp_path: object) -> None:
    """Inner use_cassette overrides the outer one; outer is restored after inner exits."""
    dir_path = str(tmp_path)
    path_outer = _make_cassette(
        os.path.join(dir_path, "outer.yaml"), "https://api.example.com/data", {"level": "outer"}
    )
    path_inner = _make_cassette(
        os.path.join(dir_path, "inner.yaml"), "https://api.example.com/data", {"level": "inner"}
    )

    with use_cassette(path_outer, record_mode="none", intercept=["httpx"]):
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.example.com/data")
            assert resp.json() == {"level": "outer"}

        with use_cassette(path_inner, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                assert resp.json() == {"level": "inner"}

        # After inner exits, outer is restored
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.example.com/data")
            assert resp.json() == {"level": "outer"}


@pytest.mark.anyio
async def test_no_cassette_passthrough() -> None:
    """When no cassette is active, requests pass through to the real transport."""
    acquire_patches([HttpxInterceptor])
    try:
        mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"passthrough": True}))
        async with httpx.AsyncClient(transport=mock_transport) as client:
            resp = await client.get("https://api.example.com/data")
        assert resp.json() == {"passthrough": True}
    finally:
        release_patches([HttpxInterceptor])


@pytest.mark.anyio
async def test_concurrent_record_and_replay(tmp_path: object) -> None:
    """One task replays from cassette A while another records to cassette B - no cross-contamination."""
    dir_path = str(tmp_path)
    path_replay = _make_cassette(
        os.path.join(dir_path, "replay.yaml"), "https://api.example.com/data", {"mode": "replay"}
    )
    path_record = os.path.join(dir_path, "record.yaml")

    async def replay_task() -> dict[str, object]:
        with use_cassette(path_replay, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    async def record_task() -> int:
        with use_cassette(path_record, record_mode="all", intercept=["httpx"]):
            transport = httpx.MockTransport(lambda request: httpx.Response(201, json={"mode": "recorded"}))
            async with httpx.AsyncClient(transport=transport) as client:
                resp = await client.get("https://api.example.com/create")
                return resp.status_code

    result_replay, status_record = await _gather(replay_task, record_task)

    assert result_replay == {"mode": "replay"}
    assert status_record == 201


@pytest.mark.anyio
async def test_concurrent_cassettes_different_urls(tmp_path: object) -> None:
    """Concurrent cassettes targeting different URLs don't interfere."""
    dir_path = str(tmp_path)
    path_a = _make_cassette(os.path.join(dir_path, "a.yaml"), "https://api-a.example.com/data", {"api": "a"})
    path_b = _make_cassette(os.path.join(dir_path, "b.yaml"), "https://api-b.example.com/data", {"api": "b"})

    async def task_a() -> dict[str, object]:
        with use_cassette(path_a, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api-a.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    async def task_b() -> dict[str, object]:
        with use_cassette(path_b, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api-b.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    result_a, result_b = await _gather(task_a, task_b)

    assert result_a == {"api": "a"}
    assert result_b == {"api": "b"}


# ---------------------------------------------------------------------------
# Thread concurrency
# ---------------------------------------------------------------------------


def test_threadpool_concurrent_cassettes(tmp_path: object) -> None:
    """Multiple threads each using their own cassette via ThreadPoolExecutor."""
    dir_path = str(tmp_path)
    n = 10

    paths = []
    for i in range(n):
        path = _make_cassette(
            os.path.join(dir_path, f"thread_{i}.yaml"),
            "https://api.example.com/data",
            {"thread": i},
        )
        paths.append(path)

    acquire_patches([HttpxInterceptor])
    try:

        def worker(index: int) -> dict[str, object]:
            cassette = Cassette(paths[index], record_mode=RecordMode.NONE)
            cassette.load()
            token = current_cassette.set(cassette)
            try:
                with httpx.Client() as client:
                    resp = client.get("https://api.example.com/data")
                    return resp.json()  # type: ignore[no-any-return]
            finally:
                current_cassette.reset(token)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, i) for i in range(n)]
            results = [f.result() for f in futures]

        for i, result in enumerate(results):
            assert result == {"thread": i}, f"thread {i} got wrong cassette: {result}"

    finally:
        release_patches([HttpxInterceptor])


def test_threadpool_with_context_propagation(tmp_path: object) -> None:
    """ThreadPoolExecutor with explicit context propagation via copy_context."""
    dir_path = str(tmp_path)
    path = _make_cassette(os.path.join(dir_path, "ctx.yaml"), "https://api.example.com/data", {"propagated": True})

    with use_cassette(path, record_mode="none", intercept=["httpx"]):
        # Copy current context (which has cassette set) and run in thread
        ctx = contextvars.copy_context()

        def work() -> dict[str, object]:
            with httpx.Client() as client:
                resp = client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ctx.run, work)
            result = future.result()

    assert result == {"propagated": True}


def test_threadpool_no_cassette_in_thread(tmp_path: object) -> None:
    """Without context propagation, threads have no cassette - requests pass through."""
    acquire_patches([HttpxInterceptor])
    try:

        def work() -> dict[str, object]:
            mock_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"fallback": True}))
            with httpx.Client(transport=mock_transport) as client:
                resp = client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            result = future.result()

        assert result == {"fallback": True}

    finally:
        release_patches([HttpxInterceptor])


@pytest.mark.anyio
async def test_concurrent_tasks_with_no_match_isolation(tmp_path: object) -> None:
    """NoMatchError in one task doesn't affect another concurrent task."""
    dir_path = str(tmp_path)
    path_a = _make_cassette(os.path.join(dir_path, "a.yaml"), "https://api.example.com/data", {"source": "a"})
    path_b = _make_cassette(os.path.join(dir_path, "b.yaml"), "https://api.example.com/other", {"source": "b"})

    async def task_a() -> dict[str, object]:
        with use_cassette(path_a, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

    async def task_b_fails() -> str:
        with use_cassette(path_b, record_mode="none", intercept=["httpx"]):
            async with httpx.AsyncClient() as client:
                try:
                    await client.get("https://api.example.com/data")  # wrong URL for cassette B
                    return "unexpected_success"  # pragma: no cover
                except NoMatchError:
                    return "no_match"

    result_a, result_b = await _gather(task_a, task_b_fails)

    assert result_a == {"source": "a"}
    assert result_b == "no_match"


# ---------------------------------------------------------------------------
# Ref-counting
# ---------------------------------------------------------------------------


def test_patch_refcounting() -> None:
    """Patches stay installed while any cassette is active, removed when all are done."""
    original_handle = httpx.AsyncHTTPTransport.handle_async_request
    original_init = httpx.AsyncClient.__init__

    acquire_patches([HttpxInterceptor])
    assert httpx.AsyncHTTPTransport.handle_async_request is not original_handle
    assert httpx.AsyncClient.__init__ is not original_init

    acquire_patches([HttpxInterceptor])
    assert httpx.AsyncHTTPTransport.handle_async_request is not original_handle
    assert httpx.AsyncClient.__init__ is not original_init

    release_patches([HttpxInterceptor])
    # Still patched (refcount=1)
    assert httpx.AsyncHTTPTransport.handle_async_request is not original_handle
    assert httpx.AsyncClient.__init__ is not original_init

    release_patches([HttpxInterceptor])
    # Now unpatched (refcount=0)
    assert httpx.AsyncHTTPTransport.handle_async_request is original_handle
    assert httpx.AsyncClient.__init__ is original_init


def test_thread_without_context_falls_back_to_active_cassette(tmp_path: object) -> None:
    """Threads with no propagated context see the active cassette.

    Libraries like Temporal and DBOS run workflow code on worker threads
    created outside the test's context; requests made there must still replay.
    """
    dir_path = str(tmp_path)
    path = _make_cassette(os.path.join(dir_path, "fallback.yaml"), "https://api.example.com/data", {"fallback": "hit"})

    with use_cassette(path, record_mode="none", intercept=["httpx"]):

        def work() -> dict[str, object]:
            with httpx.Client() as client:
                resp = client.get("https://api.example.com/data")
                return resp.json()  # type: ignore[no-any-return]

        # No copy_context: the worker thread has an empty context.
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(work).result()

    assert result == {"fallback": "hit"}


def test_thread_context_cassette_wins_over_fallback(tmp_path: object) -> None:
    """A cassette set in the thread's own context takes priority over the fallback."""
    dir_path = str(tmp_path)
    path_outer = _make_cassette(os.path.join(dir_path, "f-outer.yaml"), "https://api.example.com/data", {"c": "outer"})
    path_own = _make_cassette(os.path.join(dir_path, "f-own.yaml"), "https://api.example.com/data", {"c": "own"})

    with use_cassette(path_outer, record_mode="none", intercept=["httpx"]):

        def work() -> dict[str, object]:
            own = Cassette(path_own, record_mode=RecordMode.NONE)
            own.load()
            token = current_cassette.set(own)
            try:
                with httpx.Client() as client:
                    return client.get("https://api.example.com/data").json()  # type: ignore[no-any-return]
            finally:
                current_cassette.reset(token)

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(work).result()

    assert result == {"c": "own"}


def test_fallback_removed_out_of_order(tmp_path: object) -> None:
    """Exiting an earlier cassette leaves a later still-active one as the fallback."""
    from cassetter._state import get_current_cassette, pop_fallback_cassette, push_fallback_cassette

    dir_path = str(tmp_path)
    path_a = _make_cassette(os.path.join(dir_path, "ooo-a.yaml"), "https://api.example.com/data", {"c": "a"})
    path_b = _make_cassette(os.path.join(dir_path, "ooo-b.yaml"), "https://api.example.com/data", {"c": "b"})

    cassette_a = Cassette(path_a, record_mode=RecordMode.NONE)
    cassette_a.load()
    cassette_b = Cassette(path_b, record_mode=RecordMode.NONE)
    cassette_b.load()

    push_fallback_cassette(cassette_a)
    push_fallback_cassette(cassette_b)
    pop_fallback_cassette(cassette_a)
    assert get_current_cassette() is cassette_b
    pop_fallback_cassette(cassette_b)
    assert get_current_cassette() is None
