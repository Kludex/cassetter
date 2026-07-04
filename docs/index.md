# Cassetter

Cassetter is a Rust powered HTTP cassette recorder for Python tests. Safe by default.

The first time your test runs, Cassetter records the real HTTP interactions to a **cassette** file. Every run after that, it replays the recorded responses. No network needed. Fast, deterministic tests.

The key features are:

* **Safe by default**: sensitive headers, query parameters, and body fields are filtered at write time. Cassettes never contain secrets.
* **Fast**: parsing, matching, and serialization run in a Rust core. Loading cassettes is 3 to 6 times faster than VCR.py.
* **Secure**: cassette YAML is parsed in Rust. There is no way for a cassette file to execute Python code.
* **Readable cassettes**: JSON bodies are stored as structured YAML, not escaped strings. Diffs stay clean.
* **Multi protocol**: HTTP, gRPC, WebSockets, and streaming (SSE) responses.
* **Drop in**: designed as a replacement for VCR.py and pytest-recording, with the same `@pytest.mark.vcr` marker.

## Requirements

Python 3.10+

Cassetter has no required runtime dependencies. It intercepts the HTTP libraries you already have installed.

## Installation

```console
$ uv add cassetter
```

Or with pip:

```console
$ pip install cassetter
```

## Example

Mark a test with `@pytest.mark.vcr`:

```python
import httpx
import pytest


@pytest.mark.vcr(record_mode="once")
async def test_get_users():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/users")
    assert response.status_code == 200
```

Now run it:

```console
$ pytest
```

The first run performs the real request and saves the interaction to `tests/cassettes/test_get_users/test_get_users.yaml`.

Run it again. This time the response comes from the cassette. No network. Same result.

That's it.

## What the cassette looks like

Open the file. It is plain YAML, and JSON bodies are stored as structure, not as escaped strings:

```yaml
version: 1
interactions:
  - request:
      method: GET
      uri: https://api.example.com/users
      headers:
        accept:
          - '*/*'
    response:
      status: 200
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          users:
            - id: 1
              name: Alice
    recorded_at: '2026-02-20T10:30:01Z'
```

Notice what is **not** there: no `authorization` header, no cookies, no API keys. Cassetter strips them before writing. You will read more about it in [Safe by default](tutorial/security.md).

## Supported libraries

| Library | Protocol |
|---------|----------|
| httpx | HTTP |
| aiohttp | HTTP |
| requests | HTTP |
| urllib3 | HTTP |
| pyreqwest-impersonate | HTTP |
| grpcio | gRPC |
| websockets | WebSocket |

Cassetter detects which libraries are installed and intercepts them automatically. You can also select them explicitly, see [Use the context manager](tutorial/context-manager.md).

## License

This project is licensed under the terms of the MIT license.
