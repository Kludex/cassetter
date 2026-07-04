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
