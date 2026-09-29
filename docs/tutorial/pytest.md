# Use it with pytest

Cassetter ships with a pytest plugin. It is installed and activated automatically, you don't need to configure anything.

## Mark a test

Add the `@pytest.mark.vcr` marker to any test that makes HTTP requests:

```python
import httpx
import pytest


@pytest.mark.vcr
async def test_api_call():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/users")
    assert response.status_code == 200
```

Each marked test gets its own cassette file at:

```
{test_dir}/cassettes/{test_file_stem}/{test_name}.yaml
```

For a test `test_api_call` in `tests/test_users.py`, that is `tests/cassettes/test_users/test_api_call.yaml`.

For tests inside a class, the class name is included: `TestUsers.test_api_call.yaml`.

## Record the cassette

By default the plugin runs in the `none` record mode: replay only, never touch the network. To record cassettes for the first time, pass `--record-mode`:

```console
$ pytest --record-mode=once
```

After that, run pytest normally and the tests replay from the cassettes.

!!! tip
    Keeping `none` as the default is intentional. Your test suite will fail loudly if a cassette is missing or stale, instead of silently making real requests in CI.

You can read about all the modes in [Record modes](record-modes.md).

## Access the cassette

If you need to inspect the recorded interactions, request the `cassette` fixture:

```python
from cassetter import Cassette


@pytest.mark.vcr
async def test_with_cassette(cassette: Cassette):
    async with httpx.AsyncClient() as client:
        await client.get("https://api.example.com/users")
    assert len(cassette.interactions) == 1
```

The fixture is also available under the name `vcr`, for compatibility with pytest-recording.

The cassette exposes vcrpy's introspection surface, so wire-contract assertions port over unchanged: `cassette.requests` returns the recorded requests with `.method`, `.uri`, `.headers`, `.body`, `.path`, `.host`, and `.query` attributes, and `cassette.play_count`, `cassette.play_counts`, and `cassette.all_played` report replay progress.

`play_count`, `play_counts`, and `played_indices` count HTTP interactions only, as in vcrpy. `all_played` covers every protocol. For gRPC and WebSocket interactions, use `grpc_played_indices` and `ws_played_indices`:

```python
@pytest.mark.vcr
async def test_uses_every_recording(cassette: Cassette):
    ...
    assert all(cassette.ws_played_indices)
    assert cassette.all_played
```

!!! note "A WebSocket interaction counts as played once its connection opens"
    `ws_played_indices` does not say whether every recorded frame was received.

```python
@pytest.mark.vcr
async def test_sends_tool_definitions(cassette: Cassette):
    ...
    request_body = json.loads(cassette.requests[0].body)
    assert request_body["tools"][0]["name"] == "get_weather"
```

`cassette.requests` is what the cassette recorded, so it keeps passing after the code stops sending a field: the default matcher ignores the body. `cassette.sent_requests` is what the code sent during this test, replayed or live, with the same attributes. Assert on it to catch that drift:

```python
@pytest.mark.vcr
async def test_sends_tool_definitions(cassette: Cassette):
    ...
    request_body = json.loads(cassette.sent_requests[0].body)
    assert request_body["tools"][0]["name"] == "get_weather"
```

!!! warning "`sent_requests` holds credentials"
    Requests are captured before `before_record_request` and scrubbing, so their headers and bodies still hold API keys. They stay in memory and are never written to the cassette. Requests to bypassed hosts are not captured, and only HTTP requests are.

## Configure with `vcr_config`

Override the `vcr_config` fixture to set options for a whole module:

```python
import pytest


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "record_mode": "once",
        "match_on": ["method", "uri", "json_body"],
        "filter_headers": ["x-custom-secret"],
        "ignore_hosts": ["*.googleapis.com"],
    }
```

The supported keys are the same options accepted by `use_cassette()`:

| Key | Description |
|-----|-------------|
| `record_mode` | Recording behavior, see [Record modes](record-modes.md) |
| `match_on` | Fields used to match requests |
| `ignore_json_paths` | JSON paths ignored during matching |
| `filter_headers` | Headers stripped from cassettes |
| `filter_query_parameters` | Query params replaced in cassettes |
| `body_scrub_patterns` | Body field patterns scrubbed from cassettes |
| `filter_replacement` | Replacement string for filtered values |
| `cassette_dir` | Cassette directory, relative to the test file |
| `cassette_library_dir` | Cassette directory, used as is |
| `intercept` | Libraries to intercept |
| `max_age` | Cassette expiry, e.g. `"30d"` |
| `on_expiry` | What to do with expired cassettes |
| `ignore_localhost` | Bypass requests to localhost |
| `ignore_hosts` | Bypass requests to matching hosts |
| `before_record_request` | Hook to modify or skip requests |
| `before_record_response` | Hook to modify or skip responses |
| `uri_normalizer` | Callable applied to both URIs before matching |
| `before_record_ws_frame` | Hook to modify or skip WebSocket frames |

The fixture can also return a [`Cassetter`](configuration.md), which is the same set of options as an object, shareable with code that calls `use_cassette()` directly:

```python
from cassetter import Cassetter


@pytest.fixture(scope="module")
def vcr_config() -> Cassetter:
    return Cassetter(record_mode="once", filter_headers=["x-custom-secret"])
```

## Configure per test

The marker accepts overrides for a single test:

```python
@pytest.mark.vcr("custom_name.yaml", record_mode="all")
async def test_special_case(): ...
```

The first positional argument sets the cassette file name. The keyword arguments `record_mode`, `cassette_dir`, `max_age`, `on_expiry`, `ignore_hosts`, and `match_on` override the module configuration for that test:

```python
@pytest.mark.vcr(ignore_hosts=["gateway.example"], match_on=["method", "uri", "json_body"])
async def test_gateway(): ...
```

`additional_matchers` appends to the module's `match_on` instead of replacing it, as it does in VCR.py:

```python
@pytest.mark.vcr(additional_matchers=["body"])
async def test_sends_the_recorded_body(): ...
```

!!! warning "Unknown marker options fail the test"
    A marker option Cassetter does not support raises `TypeError` instead of being dropped. A dropped `additional_matchers` or `ignore_hosts` would weaken the test without telling you.

pytest-recording's `default_cassette` marker names the cassette too, so suites that already use it keep working:

```python
@pytest.mark.default_cassette("custom_name.yaml")
@pytest.mark.vcr
async def test_special_case(): ...
```

The positional argument wins if a test carries both. Either way the name is resolved against the cassette directory, so pass a name rather than a path.

The command line flag `--record-mode` overrides everything.

## Customize the cassette directory

Override the `vcr_cassette_dir` fixture:

```python
@pytest.fixture(scope="module")
def vcr_cassette_dir():
    return "tests/my_cassettes"
```

## Find orphaned cassettes

Over time, tests get renamed and deleted, and their cassettes stay behind. Find cassette files that no test uses:

```console
$ pytest --vcr-check-orphans=tests/cassettes/
```
