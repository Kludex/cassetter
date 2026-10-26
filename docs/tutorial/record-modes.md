# Record modes

The record mode controls what happens when a request is made under an active cassette.

| Mode | Behavior |
|------|----------|
| `none` | Replay only. Raises `NoMatchError` if no recorded interaction matches. |
| `once` | Record if the cassette doesn't exist. Replay if it does. |
| `new_episodes` | Replay existing interactions. Record new ones. |
| `all` | Record everything, overwriting the cassette. |
| `rewrite` | Delete the cassette, then record everything. |
| `verify` | Send matched requests live. Raise `ResponseMismatchError` if the response differs from the recording. |

## `none`

Use it in CI and for day to day test runs. Nothing touches the network. If a request has no matching interaction in the cassette, the test fails with `NoMatchError`.

```python
with use_cassette("cassette.yaml", record_mode="none"):
    ...
```

## `once`

Use it while developing. The first run records, every run after that replays.

```python
with use_cassette("cassette.yaml", record_mode="once"):
    ...
```

This is the default for `use_cassette()`.

## `new_episodes`

Use it when you add new requests to an existing test. Matched requests replay from the cassette, unmatched requests go to the real server and get appended.

```python
with use_cassette("cassette.yaml", record_mode="new_episodes"):
    ...
```

## `all`

Use it to re-record a cassette from scratch, for example after an API change.

```python
with use_cassette("cassette.yaml", record_mode="all"):
    ...
```

## `rewrite`

Same as `all`, except the cassette file is deleted before the test runs. A test that no longer makes the request it used to leaves no cassette behind, instead of leaving an empty one.

```python
with use_cassette("cassette.yaml", record_mode="rewrite"):
    ...
```

## `verify`

Use it when the cassette is the expected output of the service under test, not a stand-in for a dependency. For example, when you port an HTTP API to another language: record the reference implementation once, then check the new one against it.

```python
import httpx2
from cassetter import Cassetter, Compare

cassetter = Cassetter(
    cassette_library_dir="tests/expected",
    match_on=["method", "uri", "body"],
    compare=Compare(
        headers=["content-type", "x-price-*"],
        json_ignore=["id", "created"],
        float_tolerance=1e-9,
    ),
)

# Against the reference implementation.
with cassetter.use_cassette("chat.yaml", record_mode="rewrite"):
    httpx2.post("http://localhost:8000/v1/chat", json={"model": "m", "messages": []})

# Against the new implementation.
with cassetter.use_cassette("chat.yaml", record_mode="verify"):
    httpx2.post("http://localhost:8000/v1/chat", json={"model": "m", "messages": []})
```

Matching works as in `none`: `match_on` picks the recording, and a request without one raises `NoMatchError`. The difference is what happens after a match. The request goes to the network, the response goes through the same hooks, decompression and scrubbing as a recording, and is compared to the recorded one. The cassette is never written.

`Compare` decides what counts as equivalent:

| Field | Compared |
|-------|----------|
| status | Always, exactly. |
| `headers` | Only the listed names, by value. Globs such as `x-price-*` are allowed. `date`, `server` and every other header are ignored. |
| `json_ignore` | JSON bodies are compared structurally, without these paths. Same syntax as `ignore_json_paths`: `id`, `data.created`, `items[0].id`. |
| `float_tolerance` | Largest difference between two JSON numbers that still counts as equal. |
| `sse` | Compare the body as the list of Server-Sent Events `data:` payloads, so chunk boundaries and comments do not matter. JSON payloads are parsed, and `json_ignore` applies to each. |

Any other body is compared as text or bytes.

On a difference, the test fails with a unified diff of both responses, as compared:

```
cassette tests/expected/chat.yaml, interaction 0 (POST http://localhost:8000/v1/chat)
--- recorded
+++ live
@@ -1,7 +1,7 @@
 status: 200
 @@ headers @@
 content-type: application/json
-x-price-estimate: 0.0001USD
+x-price-estimate: 0.0002USD
 @@ body @@
 {
   "content": "hi"
```

!!! tip "Normalize what `Compare` cannot express"
    `before_compare_response` receives the recorded and the live `HttpResponse` and returns both, normalized. For example, to treat an absent key and a `null` value as equal:

    ```python
    from cassetter import Body, HttpResponse


    def drop_nulls(recorded: HttpResponse, live: HttpResponse) -> tuple[HttpResponse, HttpResponse]:
        def clean(response: HttpResponse) -> HttpResponse:
            content = {key: value for key, value in response.body.content.items() if value is not None}
            return response.replace(body=Body("json", content))

        return clean(recorded), clean(live)
    ```

## Set the mode from the command line

With the pytest plugin, `--record-mode` overrides whatever the tests configure:

```console
$ pytest --record-mode=once
```

A common workflow:

* Locally, record new cassettes with `pytest --record-mode=once`.
* In CI, run plain `pytest`. The plugin default is `none`, so CI never makes real requests.
