# Reuse a configuration

Passing the same options to every `use_cassette()` call gets old fast. `Cassetter` holds them once:

```python
from cassetter import Cassetter

recorder = Cassetter(
    cassette_library_dir="tests/cassettes",
    record_mode="none",
    filter_headers=["x-gateway-apikey"],
    match_on=["method", "uri", "json_body"],
)

with recorder.use_cassette("openai.yaml"):
    ...

with recorder.use_cassette("anthropic.yaml"):
    ...
```

It accepts every option `use_cassette()` accepts, plus `cassette_library_dir`. Anything you leave out keeps its default.

The object is callable, so `recorder("openai.yaml")` is the same as `recorder.use_cassette("openai.yaml")`.

## Where the cassettes go

`cassette_library_dir` is the directory cassette names are resolved against:

```python
recorder = Cassetter(cassette_library_dir="src/evals/cassettes")

with recorder.use_cassette("openai.yaml"):  # src/evals/cassettes/openai.yaml
    ...
```

Names can include subdirectories, and an absolute path is used as is. Without `cassette_library_dir`, the name is the path, exactly like `use_cassette()`.

## Override one cassette

Keyword arguments to `use_cassette()` replace the configured value for that cassette only:

```python
recorder = Cassetter(cassette_library_dir="tests/cassettes", record_mode="none")

with recorder.use_cassette("openai.yaml", record_mode="all"):
    ...  # re-records this one cassette
```

`Cassetter` is frozen, so no test can reassign an option on a configuration another test shares. To derive a new configuration instead of overriding a single call, use `dataclasses.replace`:

```python
from dataclasses import replace

recording = replace(recorder, record_mode="all")
```

## Share it with pytest

The `vcr_config` fixture accepts a `Cassetter`, so the same object drives both the marked tests and any direct `use_cassette()` call:

```python
# tests/conftest.py
import pytest

from cassetter import Cassetter

RECORDER = Cassetter(record_mode="none", filter_headers=["x-gateway-apikey"])


@pytest.fixture(scope="module")
def vcr_config() -> Cassetter:
    return RECORDER
```

Two things behave differently under pytest, matching what the plugin already does with a dictionary:

* An unset `record_mode` means `none`, not `once`. Cassettes never record unless you pass `--record-mode`.
* `cassette_library_dir`, when set, replaces the [`vcr_cassette_dir`](pytest.md#customize-the-cassette-directory) fixture, so cassettes are not grouped per test module. A `cassette_dir` on the marker still wins.
