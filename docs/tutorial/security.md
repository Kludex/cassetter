# Safe by default

Here is a story that happens all the time: a developer records a cassette, the `authorization` header goes into the YAML file, the file gets committed, and now there is an API token in the git history. Forever.

Cassetter is designed so this cannot happen. Sensitive data is filtered **at write time**. The secrets never reach the disk, so there is nothing to leak.

## What is filtered

These request and response **headers** are stripped automatically:

`authorization`, `cookie`, `set-cookie`, `x-api-key`, `api-key`, `x-auth-token`, `proxy-authorization`, `www-authenticate`, `x-goog-api-key`, `x-amz-security-token`

These **query parameters** are replaced with `[FILTERED]`:

`api_key`, `apikey`, `token`, `access_token`, `client_secret`

These **JSON body fields** are scrubbed, at any nesting level:

`password`, `access_token`, `refresh_token`, `client_secret`

The same rules apply to every protocol:

* HTTP: headers, query parameters, and bodies.
* gRPC: request and response metadata, and the `json_debug` payload.
* WebSockets: handshake headers and text or JSON frame bodies.

Binary protobuf bodies are stored as is. They cannot be pattern scrubbed.

## See it in action

Record a request with credentials:

```python
with use_cassette("cassette.yaml", record_mode="once"):
    httpx.post(
        "https://api.example.com/login?api_key=super-secret",
        headers={"authorization": "Bearer token123"},
        json={"username": "alice", "password": "hunter2"},
    )
```

This is what lands in the cassette:

```yaml
interactions:
  - request:
      method: POST
      uri: https://api.example.com/login?api_key=[FILTERED]
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          username: alice
          password: '[FILTERED]'
```

No `authorization` header. No API key. No password.

## Customize the filters

Add your own headers, patterns, and replacement string:

```python
with use_cassette(
    "cassette.yaml",
    filter_headers=["x-custom-secret"],
    filter_query_parameters=["signature"],
    body_scrub_patterns=["my_secret_field"],
    filter_replacement="***REDACTED***",
):
    ...
```

`filter_headers`, `filter_query_parameters` and `body_scrub_patterns` **add to** the built-in lists rather than replacing them. Naming one more header to scrub is never a request to start recording the rest, so the defaults survive. Repeats are ignored, case insensitively.

The lists themselves are importable as `DEFAULT_FILTER_HEADERS`, `DEFAULT_FILTER_QUERY_PARAMS` and `DEFAULT_BODY_SCRUB_PATTERNS`.

!!! note
    To define a list outright - to stop filtering something built in, say, because a test asserts on it - assign the attribute on a `SecurityConfig`:

    ```python
    from cassetter import SecurityConfig

    config = SecurityConfig()
    config.filter_headers = ["only-this"]
    ```

Body scrub patterns are matched case insensitively against JSON keys, at any depth. A pattern matches if the key contains it, so `token` matches `access_token` and `refresh_token` too.

## YAML safety

There is a second security angle to cassettes: loading them.

VCR.py parses cassettes with an unsafe YAML loader that supports `!!python/object` tags. A malicious cassette file can execute arbitrary Python code when loaded.

Cassetter parses YAML in Rust with [serde-saphyr](https://crates.io/crates/serde-saphyr), a parser built for hostile input: no `unsafe` code, panic-free on malformed documents, and hard budgets on aliases and nesting, so a malicious cassette cannot trigger code execution or a billion laughs attack. A cassette file is only ever data.
