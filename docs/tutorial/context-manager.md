# Use the context manager

If you are not using pytest, or you want explicit control, use `use_cassette()` directly:

```python
import httpx

from cassetter import use_cassette

with use_cassette("tests/cassettes/my_test.yaml", record_mode="once"):
    with httpx.Client() as client:
        response = client.get("https://api.example.com/users")
```

Everything inside the `with` block is recorded or replayed. When the block exits, the cassette is saved.

The context manager yields the cassette, so you can inspect it:

```python
with use_cassette("cassette.yaml", record_mode="once") as cassette:
    ...
    print(len(cassette.interactions))
```

!!! note
    `use_cassette()` defaults to the `once` record mode: record if the cassette doesn't exist, replay if it does. The pytest plugin defaults to `none` instead.

## All the options

```python
with use_cassette(
    "cassette.yaml",
    record_mode="once",
    match_on=["method", "uri"],
    ignore_json_paths=["request_id"],
    filter_headers=["x-custom-secret"],
    filter_query_parameters=["signature"],
    body_scrub_patterns=["my_secret_field"],
    filter_replacement="[FILTERED]",
    intercept=["httpx", "aiohttp"],
    max_age="30d",
    on_expiry="warn",
    ignore_localhost=True,
    ignore_hosts=["*.googleapis.com"],
    before_record_request=my_request_hook,
    before_record_response=my_response_hook,
):
    ...
```

Each option has its own section in this tutorial. The important thing to remember: **you only need the path**. Everything else has safe defaults.

!!! tip
    To declare these options once and reuse them across many cassettes, see [Reuse a configuration](configuration.md).

## Select the intercepted libraries

By default, Cassetter detects which HTTP libraries are installed and intercepts all of them. To limit interception to specific libraries, pass `intercept`:

```python
with use_cassette("cassette.yaml", intercept=["httpx"]):
    ...
```

The available names are `httpx`, `httpx2`, `aiohttp`, `requests`, `urllib3`, `pyreqwest`, `grpc`, and `websockets`.

!!! tip
    gRPC and WebSocket interception are not part of auto detection. Add `"grpc"` or `"websockets"` explicitly when you need them. See [gRPC](../protocols/grpc.md) and [WebSockets](../protocols/websockets.md).

## Nesting

Cassettes can be nested. The inner cassette takes over while its block is active, and the outer one is restored when it exits:

```python
with use_cassette("outer.yaml"):
    ...  # recorded to outer.yaml
    with use_cassette("inner.yaml"):
        ...  # recorded to inner.yaml
    ...  # recorded to outer.yaml again
```
