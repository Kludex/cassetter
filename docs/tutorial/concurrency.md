# Concurrency

Multiple cassettes can be active at the same time in the same process. Each `use_cassette()` context gets its own isolated cassette through a `contextvars.ContextVar`.

This works out of the box with `asyncio.gather`, `anyio` task groups, and any framework that creates async tasks:

```python
import asyncio

import httpx

from cassetter import use_cassette


async def task_a():
    with use_cassette("cassettes/a.yaml", record_mode="none"):
        async with httpx.AsyncClient() as client:
            return await client.get("https://api.example.com/data")


async def task_b():
    with use_cassette("cassettes/b.yaml", record_mode="none"):
        async with httpx.AsyncClient() as client:
            return await client.get("https://api.example.com/data")


results = await asyncio.gather(task_a(), task_b())
```

Each task records to and replays from its own cassette. No cross contamination.

This matters in practice: evaluation frameworks like Pydantic Evals run cases with `max_concurrency > 1`, and each case can have its own cassette.

## Threads

Threads are different. A `contextvars` context does not propagate into a `ThreadPoolExecutor` automatically, so by default a thread sees **no active cassette** and its requests pass through to the real server.

To propagate the cassette into a thread, copy the context explicitly:

```python
import contextvars
from concurrent.futures import ThreadPoolExecutor

import httpx

from cassetter import use_cassette

with use_cassette("cassette.yaml", record_mode="none"):
    ctx = contextvars.copy_context()

    def work():
        with httpx.Client() as client:
            return client.get("https://api.example.com/data")

    with ThreadPoolExecutor() as pool:
        future = pool.submit(ctx.run, work)
        result = future.result()
```

The key part is `ctx.run(work)`: the thread executes `work` inside the copied context, where the cassette is active.

## Recorded order is stable

Concurrent requests come back in whatever order the network decides, so recording them in arrival order would rewrite the cassette every time the timings shift. Cassettes are written in a canonical order instead: interactions are sorted by the fields you [match on](matching.md), and re-recording a suite produces the same file whichever response happened to land first.

Interactions the matcher cannot tell apart are left alone, because their order is what decides which one replays: with the default `["method", "uri"]`, two calls to the same URL replay in the order they appear. Those keep the order their requests were *sent* in, which is stable across runs even when completion order is not.

!!! note
    The order is canonical for the `match_on` in force while recording. Narrowing `match_on` afterwards - say from `["method", "uri", "json_body"]` to `["method", "uri"]` - can make interactions that used to be distinct interchangeable, and the file is no longer ordered for the new matcher. Re-record after changing it.
