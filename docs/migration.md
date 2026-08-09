# Migrate from VCR.py

Cassetter is designed as a drop in replacement for VCR.py and pytest-recording. Most projects migrate with minimal changes.

## Your cassettes keep working

Existing VCR cassettes work as is. Cassetter reads both the VCR format and its own format.

When a cassette is re-recorded, it is written in Cassetter's format, with structured JSON bodies instead of escaped strings.

To bulk convert cassettes without re-recording, use the CLI. In place, keeping YAML:

```console
$ cassetter convert tests/cassettes/ yaml --force
```

Or changing the format to TOML:

```console
$ cassetter convert tests/cassettes/ toml
```

Conversion applies the default security filtering, so any secrets VCR.py recorded (it keeps `authorization` headers by default) are removed on the way through. Pass `--no-scrub` to skip that. See [Cassette formats](tutorial/formats.md) for the details.

## Your markers keep working

Cassetter uses the same `@pytest.mark.vcr` marker, the same `vcr_config` fixture, and the same `--record-mode` command line flag as pytest-recording. In many projects, the migration is:

```console
$ uv remove vcrpy pytest-recording
$ uv add cassetter
$ pytest
```

## What changed

| pytest-recording / VCR.py | Cassetter | Notes |
|---|---|---|
| `vcr` fixture | `cassette` fixture | `vcr` still works as an alias |
| `vcr.VCR(...)` | [`Cassetter(...)`](tutorial/configuration.md) | Same idea, same `cassette_library_dir`, and it can be returned from `vcr_config` |
| `vcr_cassette_dir` fixture | `vcr_cassette_dir` fixture | Same name, same behavior |
| `filter_query_parameters` | `filter_query_parameters` | Same name |
| `before_record_request` | `before_record_request` | Same name. Receives a `RawRequest`, and raises `SkipRecording` where VCR.py returns `None`. Runs on live requests only - see below |
| `before_record_response` | `before_record_response` | Same name. Receives a `RawResponse` dataclass, not the response dict VCR.py passes, so `response['headers']` becomes `response.headers`. Discard a response by raising `SkipRecording`, not by returning `None` |
| `cassette.requests`, `play_count`, `play_counts`, `all_played`, `len(cassette)` | Same names | vcrpy-style introspection on the cassette object |
| `decode_compressed_response` | automatic | Responses are always decompressed |
| `filter_post_data_parameters` | `body_scrub_patterns` | Pattern based instead of parameter name based |

## What is intentionally different

Filtering is **on by default**. VCR.py records `authorization` headers unless you configure `filter_headers` yourself. Cassetter strips the common sensitive headers, query parameters, and body fields without any configuration. If you relied on credentials being in the cassette (for example, asserting on them), you will need to adjust those tests.

`filter_headers`, `filter_query_parameters` and `body_scrub_patterns` **add to** those built-in lists. VCR.py replaces its own, but its defaults are empty, so passing a list there means "filter this" and here means "filter this too". See [Safe by default](tutorial/security.md#customize-the-filters) for how to define a list outright.

`before_record_request` runs on requests as they go out, not on interactions as they are read back. VCR.py applies it in both directions, so a hook that drops a request also drops any matching interaction already recorded in a cassette; under Cassetter that recording survives, and stays unplayable. If you skip a request that older cassettes still contain - an OAuth token exchange, say - delete those interactions when you migrate.

## Known limitation

A raw JSON request body whose keys are exactly `type` and `content`, with `type` equal to `json`, `text`, `binary`, or `none`, is indistinguishable from Cassetter's own body envelope and is read as the envelope. If an API you record uses that exact payload shape, re-record the cassette with Cassetter (which stores the payload inside the envelope) instead of converting it.

## Not supported

Some VCR.py features have no Cassetter equivalent yet:

* `before_playback_response`: modifying responses during playback.
* `allow_playback_repeats`: replaying the same interaction multiple times.
* `record_on_exception`: skipping the save when the test raises.
* Custom matchers via `register_matcher`. The most common use case - erasing
  URI differences such as regions or account IDs - is covered by
  `uri_normalizer`, a callable applied to both recorded and incoming URIs
  before comparison.
* `@pytest.mark.block_network` and `--disable-recording`.

If you depend on one of these, open an issue and tell us about your use case.

## Threads

VCR.py patches HTTP clients globally, so requests made from any thread replay
from the active cassette. Cassetter tracks the active cassette in a
`ContextVar` for concurrency isolation, and falls back to the active cassette
in threads whose context is empty - e.g. worker threads spawned by Temporal or
DBOS that don't propagate contextvars. The net effect matches VCR.py: while a
single cassette is active, requests from any thread replay from it.

The fallback applies only when exactly one cassette is active. A thread with an
empty context cannot say which `use_cassette` block it belongs to, so with
several active at once - concurrent blocks in different tasks, or a nested one -
it inherits none and its requests are not replayed. Propagate the context with
`contextvars.copy_context()` where you need a cassette in those threads.
