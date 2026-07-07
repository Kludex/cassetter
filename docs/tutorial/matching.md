# Request matching

When a request is made under an active cassette, Cassetter searches the recorded interactions for one that **matches**. If it finds one, it replays the recorded response. Each interaction is replayed at most once, in order.

By default, requests match on **method** and **URI**. That is predictable and sufficient for most tests.

## Configure the matchers

Pass `match_on` with the fields you want:

```python
with use_cassette(
    "cassette.yaml",
    match_on=["method", "uri", "json_body"],
):
    ...
```

The available matchers:

| Matcher | Matches on |
|---------|-----------|
| `method` | HTTP method (`GET`, `POST`, ...) |
| `uri` | Full URI, including the query string |
| `headers` | Request headers (recorded headers must be a subset) |
| `body` | Raw request body |
| `json_body` | Request body parsed as JSON |

## Ignore volatile JSON fields

APIs love to include request IDs, timestamps, and other values that change on every call. If you match on `json_body`, those fields would break every replay.

Ignore them with `ignore_json_paths`:

```python
with use_cassette(
    "cassette.yaml",
    match_on=["method", "uri", "json_body"],
    ignore_json_paths=["request_id", "timestamp"],
):
    ...
```

Now two bodies that differ only in `request_id` and `timestamp` are considered equal.

!!! tip
    Start with the default `["method", "uri"]`. Only add `json_body` when your test makes several requests to the same URI with different payloads and you need to tell them apart.

## Normalize URIs before matching

Some URI differences are noise: an AWS request carries the region in the hostname, an ARN embeds an account ID, and a cassette recorded in one environment should still replay in another. Pass a `uri_normalizer` callable and it is applied to **both** the recorded and the incoming URI before comparison:

```python
import re

def normalize(uri: str) -> str:
    return re.sub(r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com", "bedrock-runtime.REGION.amazonaws.com", uri)

with use_cassette("cassette.yaml", uri_normalizer=normalize):
    ...
```

Now a cassette recorded against `us-east-2` replays for a request to `us-east-1`. Because the normalizer runs on both sides, cassettes on disk are never rewritten — matching just sees the normalized form.

In the pytest plugin, set it in your `vcr_config` fixture:

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {"uri_normalizer": normalize}
```

## Matching and security filtering

Cassettes are stored with sensitive values filtered, so the live request is passed through the same filters before matching. A request recorded as `?api_key=[FILTERED]` matches the real request carrying the actual key, and a scrubbed `password` field in a stored JSON body matches the real payload. Filtering never breaks replay.
