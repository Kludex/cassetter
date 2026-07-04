# Cassette expiry

Cassettes rot. The API adds a field, renames another, and your tests keep passing against a response from six months ago.

Set `max_age` to catch that:

```python
with use_cassette("cassette.yaml", max_age="30d", on_expiry="rerecord"):
    ...
```

`max_age` accepts durations like `"24h"`, `"7d"`, `"4w"`. When the cassette is older than that, `on_expiry` decides what happens:

| Action | Behavior |
|--------|----------|
| `warn` | Emit a `CassetteExpiredWarning` (the default) |
| `fail` | Raise `CassetteExpiredError` |
| `rerecord` | Delete the cassette and record it again |

## With pytest

Configure it for a module through `vcr_config`:

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {"max_age": "30d", "on_expiry": "warn"}
```

Or per test, through the marker:

```python
@pytest.mark.vcr(max_age="7d", on_expiry="fail")
async def test_fresh_data():
    ...
```

!!! tip
    A good setup: `on_expiry="warn"` in CI so nothing breaks unexpectedly, and an occasional local run with `--record-mode=all` to refresh everything.
