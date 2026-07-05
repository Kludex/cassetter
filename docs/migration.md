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
| `vcr_cassette_dir` fixture | `vcr_cassette_dir` fixture | Same name, same behavior |
| `filter_query_parameters` | `filter_query_parameters` | Same name |
| `before_record_request` | `before_record_request` | Same name, same behavior |
| `before_record_response` | `before_record_response` | Same name, same behavior |
| `cassette.requests`, `play_count`, `play_counts`, `all_played` | Same names | vcrpy-style introspection on the cassette object |
| `decode_compressed_response` | automatic | Responses are always decompressed |
| `filter_post_data_parameters` | `body_scrub_patterns` | Pattern based instead of parameter name based |

## What is intentionally different

Filtering is **on by default**. VCR.py records `authorization` headers unless you configure `filter_headers` yourself. Cassetter strips the common sensitive headers, query parameters, and body fields without any configuration. If you relied on credentials being in the cassette (for example, asserting on them), you will need to adjust those tests.

## Not supported

Some VCR.py features have no Cassetter equivalent yet:

* `before_playback_response`: modifying responses during playback.
* `allow_playback_repeats`: replaying the same interaction multiple times.
* `record_on_exception`: skipping the save when the test raises.
* Custom matchers via `register_matcher`.
* `@pytest.mark.block_network` and `--disable-recording`.

If you depend on one of these, open an issue and tell us about your use case.
