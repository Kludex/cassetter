# Cassetter

Rust-powered HTTP cassette recorder for Python tests. Safe by default.

## Why?

VCR.py works, but has fundamental problems:

- **Unsafe by default** - doesn't filter sensitive headers, tokens, or API keys
- **Unsafe YAML** - uses `yaml.load()` with an unsafe loader that can execute arbitrary Python code from cassette files
- **Slow** - pure Python YAML parsing, matching, and serialization
- **Fragile** - relies on undocumented internals that break on minor version bumps
- **Poor readability** - JSON bodies stored as escaped strings in YAML

`cassetter` fixes all of this with a Rust core (PyO3) for speed, safe-by-default security filtering, and secure YAML parsing.

## Install

```bash
uv add cassetter
```

## Quick start

### With pytest (recommended)

Mark tests with `@pytest.mark.vcr`:

```python
import httpx
import pytest

@pytest.mark.vcr
async def test_api_call():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/users")
    assert response.status_code == 200
```

First run records real HTTP interactions. Subsequent runs replay from the cassette file - no network needed.

If you need direct access to the cassette (e.g. to inspect recorded interactions), request the fixture explicitly:

```python
from cassetter import Cassette

@pytest.mark.vcr
async def test_with_cassette(cassette: Cassette):
    ...
    assert len(cassette.interactions) == 1
```

### With the context manager

```python
from cassetter import use_cassette

with use_cassette("tests/cassettes/my_test.yaml", record_mode="once"):
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/users")
```

## Record modes

| Mode | Behavior |
|------|----------|
| `none` | Replay only. Raises if no match found. |
| `once` | Record if cassette doesn't exist. Replay if it does. |
| `new_episodes` | Replay existing interactions. Record new ones. |
| `all` | Record everything, overwriting the cassette. |

Set via CLI: `pytest --record-mode=none`

## Safe by default

Sensitive data is filtered **at write time** - cassettes never contain secrets. These headers are stripped automatically:

`authorization`, `cookie`, `set-cookie`, `x-api-key`, `api-key`, `x-auth-token`, `proxy-authorization`, `www-authenticate`

Query params like `api_key`, `access_token`, `token`, `client_secret` are replaced with `[FILTERED]`.

JSON body fields like `password`, `access_token`, `refresh_token`, `client_secret` are scrubbed.

Customize filtering:

```python
from cassetter import use_cassette

with use_cassette(
    "cassette.yaml",
    filter_headers=["x-custom-secret"],
    body_scrub_patterns=["my_secret_field"],
    filter_replacement="***REDACTED***",
):
    ...
```

## Cassette format

Cassettes can be stored as **YAML** (default) or **TOML**. The format is detected by file extension (`.yaml` / `.yml` for YAML, `.toml` for TOML).

### YAML (default)

JSON bodies are stored as structured YAML - not escaped strings:

```yaml
version: 1
interactions:
  - request:
      method: POST
      uri: https://api.openai.com/v1/chat/completions
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          model: gpt-4o
          messages:
            - role: user
              content: Hello!
    response:
      status: 200
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          id: chatcmpl-abc123
          choices:
            - message:
                role: assistant
                content: Hi there!
    recorded_at: '2026-02-20T10:30:01Z'
```

### TOML

Use `.toml` extension for TOML cassettes. Body content is stored as a JSON string since TOML cannot represent null values or heterogeneous arrays:

```python
with use_cassette("cassette.toml"):
    ...
```

TOML loads ~2x faster than YAML and produces ~12% smaller files.

## Request matching

Default: match on method + URI. Configurable:

```python
from cassetter import use_cassette

with use_cassette(
    "cassette.yaml",
    match_on=["method", "uri", "json_body"],
    ignore_json_paths=["request_id", "timestamp"],
):
    ...
```

Available matchers: `method`, `uri`, `headers`, `body`, `json_body`.

## Supported libraries

| Library | Protocol | Interception method |
|---------|----------|-------------------|
| **httpx** | HTTP | `AsyncBaseTransport` / `BaseTransport` |
| **aiohttp** | HTTP | Session `_request` patch |
| **requests** | HTTP | Session `send` patch |
| **urllib3** | HTTP | `HTTPConnectionPool.urlopen` patch |
| **grpcio** | gRPC | `grpc.aio.Channel` wrapper |
| **websockets** | WebSocket | `websockets.connect` patch |

By default, interceptors are auto-detected based on which libraries are installed. To limit interception to specific libraries:

```python
with use_cassette("cassette.yaml", intercept=["httpx", "aiohttp"]):
    ...
```

## Concurrency

Multiple cassettes can run concurrently in the same process - each `use_cassette` context gets its own isolated cassette via `contextvars.ContextVar`. This works out of the box with `asyncio.gather`, `anyio.create_task_group`, and any framework that creates async tasks (e.g. Pydantic Evals with `max_concurrency > 1`).

```python
async def task_a():
    with use_cassette("cassettes/a.yaml", record_mode="none"):
        async with httpx.AsyncClient() as client:
            return await client.get("https://api.example.com/data")

async def task_b():
    with use_cassette("cassettes/b.yaml", record_mode="none"):
        async with httpx.AsyncClient() as client:
            return await client.get("https://api.example.com/data")

# Each task uses its own cassette - no cross-contamination
results = await asyncio.gather(task_a(), task_b())
```

Nested cassettes work too - the inner cassette overrides the outer, and the outer is restored when the inner exits.

### Threads

For `ThreadPoolExecutor`, each thread has its own context by default (no cassette). To propagate the current cassette into a thread, use `contextvars.copy_context()`:

```python
with use_cassette("cassette.yaml", record_mode="none"):
    ctx = contextvars.copy_context()

    def work():
        with httpx.Client() as client:
            return client.get("https://api.example.com/data")

    with ThreadPoolExecutor() as pool:
        future = pool.submit(ctx.run, work)
        result = future.result()
```

Without `copy_context()`, threads see no active cassette and requests pass through to the real server.

## gRPC support

Install the gRPC extra:

```bash
uv add "cassetter[grpc]"
```

Record and replay gRPC calls by adding `"grpc"` to the interceptor list:

```python
with use_cassette("cassette.yaml", intercept=["grpc"]):
    channel = grpc.aio.insecure_channel("localhost:50051")
    stub = my_service_pb2_grpc.MyServiceStub(channel)
    response = await stub.Echo(my_service_pb2.EchoRequest(message="hello"))
```

All four gRPC call patterns are supported: unary-unary, server streaming, client streaming, and bidirectional streaming. Request and response bodies are stored as binary in the cassette, with an optional `json_debug` section for human-readable protobuf representation (when `google.protobuf` is available):

```yaml
grpc_interactions:
  - request:
      method: /mypackage.MyService/Echo
      metadata: {}
      body:
        type: binary
        content: 0a0568656c6c6f
    response:
      status_code: 0
      status_message: OK
      metadata: {}
      body:
        type: binary
        content: 0a0568656c6c6f
    json_debug:
      request:
        message: hello
      response:
        message: hello
```

Streaming responses use length-prefixed binary encoding - multiple response chunks are stored in a single body field and decoded back into individual messages on replay.

## WebSocket support

Install the WebSocket extra:

```bash
uv add "cassetter[websockets]"
```

Record and replay WebSocket connections:

```python
with use_cassette("cassette.yaml", intercept=["websockets"]):
    async with websockets.connect("wss://ws.example.com/stream") as ws:
        await ws.send('{"subscribe": "ticker"}')
        data = await ws.recv()
```

WebSocket interactions record each frame with direction, type, and timing offset:

```yaml
ws_interactions:
  - uri: wss://ws.example.com/stream
    headers: {}
    frames:
      - direction: send
        frame_type: text
        body:
          type: text
          content: '{"subscribe": "ticker"}'
        offset_ms: 0
      - direction: recv
        frame_type: text
        body:
          type: json
          content:
            price: 42.5
        offset_ms: 120
```

On replay, `recv()` returns recorded frames in order without a real connection. `send()` is a no-op. Both text and binary frames are supported.

## Streaming / SSE support

SSE (Server-Sent Events) responses - used by OpenAI, Anthropic, Groq, and other LLM APIs for streaming - work out of the box. The full response body is recorded as readable text in the cassette:

```yaml
response:
  status: 200
  headers:
    content-type:
      - text/event-stream
  body:
    type: text
    content: |+
      data: {"id":"chatcmpl-abc","choices":[{"delta":{"role":"assistant"}}]}

      data: {"id":"chatcmpl-abc","choices":[{"delta":{"content":"Hello"}}]}

      data: [DONE]
```

On replay, the buffered body is returned to the client SDK, which parses SSE events from it. This matches how VCR.py handles streaming - chunk boundaries aren't preserved, but SSE parsers split on `\n\n` boundaries regardless of how bytes are delivered.

## Request filtering

### Ignore hosts

Bypass the cassette entirely for requests to specific hosts. Matched requests pass through to the real server - no recording, no replay:

```python
with use_cassette(
    "cassette.yaml",
    ignore_hosts=["*.googleapis.com", "accounts.google.com"],
):
    ...
```

Patterns use `fnmatch` syntax (`*` matches any sequence of characters). Combine with `ignore_localhost` for full control:

```python
with use_cassette(
    "cassette.yaml",
    ignore_localhost=True,
    ignore_hosts=["*.googleapis.com"],
):
    ...
```

### Before record request hook

Use a callback that runs before each request is recorded or replayed. Return the (possibly modified) `RawRequest`. Raise `SkipRecording` to let the request pass through live:

```python
from cassetter import RawRequest, SkipRecording, use_cassette

def my_hook(request: RawRequest) -> RawRequest:
    if not request.uri.startswith("https://api.mycompany.com"):
        raise SkipRecording
    # Strip auth header before recording
    request.headers.pop("authorization", None)
    return request

with use_cassette("cassette.yaml", before_record_request=my_hook):
    ...
```

### Before record response hook

Modify or discard responses before they are recorded. Return the (possibly modified) `RawResponse`. Raise `SkipRecording` to skip recording the interaction:

```python
from cassetter import RawResponse, SkipRecording, use_cassette

def my_hook(response: RawResponse) -> RawResponse:
    if response.status >= 500:
        raise SkipRecording  # don't record server errors
    # Strip a volatile header
    response.headers.pop("x-request-id", None)
    return response

with use_cassette("cassette.yaml", before_record_response=my_hook):
    ...
```

Both hooks work with the pytest plugin via `vcr_config`:

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {
        "ignore_hosts": ["*.googleapis.com"],
    }
```

## Cassette expiry

Force re-recording when cassettes get stale:

```python
with use_cassette("cassette.yaml", max_age="30d", on_expiry="rerecord"):
    ...
```

`max_age` accepts durations like `"24h"`, `"7d"`, `"4w"`. `on_expiry` controls the behavior:

| Action | Behavior |
|--------|----------|
| `warn` | Emit a warning (default) |
| `fail` | Raise `CassetteExpiredError` |
| `rerecord` | Delete and re-record the cassette |

Also configurable via pytest:

```ini
[tool.pytest.ini_options]
vcr_max_age = "30d"
vcr_on_expiry = "warn"
```

Or per-test:

```python
@pytest.mark.vcr(max_age="7d", on_expiry="fail")
async def test_fresh_data():
    ...
```

## Orphan detection

Find cassette files that no test uses:

```bash
pytest --vcr-check-orphans=tests/cassettes/
```

## Performance

Rust-powered YAML parsing and serialization is 3-6x faster than vcrpy (which uses PyYAML/libyaml):

```
  1000 interactions
                    cassetter    vcrpy         speedup
  load              13.53 ms          58.90 ms      4.4x
  match             0.98 ms           1.29 ms       1.3x
  save              7.58 ms           45.64 ms      6.0x
```

Run `uv run python benchmarks/bench.py` to reproduce.

## YAML safety

vcrpy uses `yaml.load()` with an unsafe loader (`CLoader`/`Loader`) that can execute arbitrary Python via `!!python/object` tags. A malicious cassette file could run code when loaded.

cassetter parses YAML in Rust, which has no concept of Python object construction - only data types are supported.

## Migrating from pytest-recording / VCR.py

cassetter is designed as a drop-in replacement. Most projects can migrate with minimal changes.

### Cassette files

Existing VCR cassettes work as-is - cassetter reads both VCR format and its own format. On the next re-record, cassettes are written in cassetter's format with structured JSON bodies instead of escaped strings.

### pytest plugin

cassetter uses the same `@pytest.mark.vcr` marker, `vcr_config` fixture, and `--record-mode` CLI flag. Key differences:

| pytest-recording / VCR.py | cassetter | Notes |
|---|---|---|
| `vcr` fixture | `cassette` fixture | `vcr` is available as an alias |
| `vcr_cassette_dir` fixture | `vcr_cassette_dir` fixture | Same name, same behavior |
| `filter_query_parameters` | `filter_query_parameters` | Same name |
| `decode_compressed_response` | _(automatic)_ | Always decompresses - no config needed |
| `before_record_response` | `before_record_response` | Same name, same behavior |
| `filter_post_data_parameters` | `body_scrub_patterns` | Regex-based instead of parameter-name-based |
| `before_record_request` | `before_record_request` | Same name, same behavior |
| `before_playback_response` | _(not supported)_ | VCR hook to modify/filter responses during playback |
| `allow_playback_repeats` | _(not supported)_ | VCR can replay the same interaction multiple times |
| `record_on_exception` | _(not supported)_ | VCR can skip saving when the test raises |
| Custom matchers | _(not supported)_ | VCR supports `register_matcher` for user-defined matching |
| `@pytest.mark.block_network` | _(not supported)_ | |
| `--disable-recording` | _(not supported)_ | |


## Development

Requires Rust toolchain and Python 3.10+.

```bash
git clone https://github.com/marcelotryle/cassetter.git
cd cassetter
uv sync
uv run maturin develop
uv run pytest
```
