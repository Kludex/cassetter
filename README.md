# vcr-but-better

Rust-powered HTTP cassette recorder for Python tests. Safe by default, no monkey-patching.

## Why?

VCR.py works, but has fundamental problems:

- **Unsafe by default** - doesn't filter sensitive headers, tokens, or API keys
- **Slow** - pure Python YAML parsing, matching, and serialization
- **Fragile** - monkey-patches library internals that break on minor version bumps
- **Poor readability** - JSON bodies stored as escaped strings in YAML

`vcr-but-better` fixes all of this with a Rust core (PyO3) for speed, safe-by-default security filtering, and stable interception via documented library extension points.

## Install

```bash
uv add vcr-but-better
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
from vcr_but_better import Cassette

@pytest.mark.vcr
async def test_with_cassette(vcr_cassette: Cassette):
    ...
    assert len(vcr_cassette.interactions) == 1
```

### With the context manager

```python
from vcr_but_better import use_cassette

async with use_cassette("tests/cassettes/my_test.yaml", record_mode="once"):
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
from vcr_but_better import use_cassette

async with use_cassette(
    "cassette.yaml",
    filtered_headers=["x-custom-secret"],
    body_scrub_patterns=["my_secret_field"],
    filter_replacement="***REDACTED***",
):
    ...
```

## Cassette format

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

## Request matching

Default: match on method + URI. Configurable:

```python
from vcr_but_better import use_cassette

async with use_cassette(
    "cassette.yaml",
    match_on=["method", "uri", "json_body"],
    ignore_json_paths=["request_id", "timestamp"],
):
    ...
```

Available matchers: `method`, `uri`, `headers`, `body`, `json_body`.

## Supported HTTP libraries

| Library | Interception method |
|---------|-------------------|
| **httpx** | `AsyncBaseTransport` / `BaseTransport` |
| **aiohttp** | Session `_request` patch |
| **requests** | Session `send` patch |

Specify which libraries to intercept:

```python
async with use_cassette("cassette.yaml", intercept=["httpx", "aiohttp"]):
    ...
```

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

## Orphan detection

Find cassette files that no test uses:

```bash
pytest --vcr-check-orphans=tests/cassettes/
```

## Development

Requires Rust toolchain and Python 3.10+.

```bash
git clone https://github.com/marcelotryle/vcr-but-better.git
cd vcr-but-better
uv sync
uv run maturin develop
uv run pytest
```

## License

MIT
