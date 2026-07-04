# Filter and skip requests

Sometimes you don't want a request in the cassette at all. Telemetry calls, authentication providers, requests to your local services. Cassetter gives you three tools for that.

## Ignore localhost

Requests to `localhost` and `127.0.0.1` pass through to the real server. No recording, no replay:

```python
with use_cassette("cassette.yaml", ignore_localhost=True):
    ...
```

This is useful when your test talks to a real local service (say, a database API in a container) and to an external API at the same time. The local traffic stays live, the external traffic goes through the cassette.

## Ignore hosts

Bypass the cassette for specific hosts, with `fnmatch` patterns:

```python
with use_cassette(
    "cassette.yaml",
    ignore_hosts=["*.googleapis.com", "accounts.google.com"],
):
    ...
```

`*` matches any sequence of characters. Matched requests pass through live.

## The `before_record_request` hook

For everything else, there is a hook. It runs before each request is recorded or replayed, and it receives a `RawRequest` you can inspect and modify:

```python
from cassetter import RawRequest, SkipRecording, use_cassette


def my_hook(request: RawRequest) -> RawRequest:
    if not request.uri.startswith("https://api.mycompany.com"):
        raise SkipRecording
    request.headers.pop("x-internal-trace", None)
    return request


with use_cassette("cassette.yaml", before_record_request=my_hook):
    ...
```

Two things you can do:

* **Modify the request** before it is recorded: strip headers, rewrite the URI, whatever you need. Return the modified request.
* **Skip it entirely**: raise `SkipRecording` and the request passes through to the real server, without recording.

## The `before_record_response` hook

The same idea, for responses:

```python
from cassetter import RawResponse, SkipRecording, use_cassette


def my_hook(response: RawResponse) -> RawResponse:
    if response.status >= 500:
        raise SkipRecording  # don't record server errors
    response.headers.pop("x-request-id", None)
    return response


with use_cassette("cassette.yaml", before_record_response=my_hook):
    ...
```

Raising `SkipRecording` here skips recording the whole interaction.

Both hooks work with the pytest plugin through `vcr_config`:

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {
        "before_record_request": my_hook,
        "ignore_hosts": ["*.googleapis.com"],
    }
```
