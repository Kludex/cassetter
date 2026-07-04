# Safe by default

Here is a story that happens all the time: a developer records a cassette, the `authorization` header goes into the YAML file, the file gets committed, and now there is an API token in the git history. Forever.

Cassetter is designed so this cannot happen. Sensitive data is filtered **at write time**. The secrets never reach the disk, so there is nothing to leak.

## What is filtered

These request and response **headers** are stripped automatically:

`authorization`, `cookie`, `set-cookie`, `x-api-key`, `api-key`, `x-auth-token`, `proxy-authorization`, `www-authenticate`

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

!!! warning
    Passing `filter_headers` **replaces** the default list, it does not extend it. If you want the defaults plus your own, get them from `SecurityConfig`:

    ```python
    from cassetter import SecurityConfig

    filter_headers=[*SecurityConfig().filter_headers, "x-custom-secret"]
    ```

Body scrub patterns are matched case insensitively against JSON keys, at any depth. A pattern matches if the key contains it, so `token` matches `access_token` and `refresh_token` too.

## YAML safety

There is a second security angle to cassettes: loading them.

VCR.py parses cassettes with an unsafe YAML loader that supports `!!python/object` tags. A malicious cassette file can execute arbitrary Python code when loaded.

Cassetter parses YAML in Rust. The Rust parser has no concept of Python object construction, only data. A cassette file can never run code.
