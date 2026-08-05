# Record modes

The record mode controls what happens when a request is made under an active cassette.

| Mode | Behavior |
|------|----------|
| `none` | Replay only. Raises `NoMatchError` if no recorded interaction matches. |
| `once` | Record if the cassette doesn't exist. Replay if it does. |
| `new_episodes` | Replay existing interactions. Record new ones. |
| `all` | Record everything, overwriting the cassette. |
| `rewrite` | Delete the cassette, then record everything. |

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

## Set the mode from the command line

With the pytest plugin, `--record-mode` overrides whatever the tests configure:

```console
$ pytest --record-mode=once
```

A common workflow:

* Locally, record new cassettes with `pytest --record-mode=once`.
* In CI, run plain `pytest`. The plugin default is `none`, so CI never makes real requests.
