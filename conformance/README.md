# Cross-language conformance

Every cassetter SDK must read and write the same cassette data.
The shared fixtures in this directory are the contract between implementations.

## Fixture sets

| Directory | Purpose |
|---|---|
| `format/` | Cassette parsing and save-and-reload compatibility. |
| `format/invalid/` | Malformed cassettes that every SDK must reject. |
| `matching/` | Request matcher behavior and repeated playback. |
| `filtering/` | Default and custom filtering across every protocol. |
| `body-processing/` | Body detection, Unicode normalization, and compression. |
| `record-modes/` | Replay, recording, replacement, and empty-run behavior. |

Each behavior directory contains shared input data and expected results.
The SDK tests read the same files directly.

The format fixtures cover:

- Every body type.
- Multi-value headers and metadata.
- Unicode text and nested JSON.
- HTTP, gRPC, and WebSocket interactions.
- YAML and TOML storage.
- VCR.py status, header, body, and `parsed_body` migration.
- Empty cassettes.
- Missing required gRPC and WebSocket fields.
- Malformed TOML body content.
- Unknown top-level and interaction fields.

The behavior fixtures cover:

- Default and configurable request matching.
- Header subsets, typed bodies, ignored JSON paths, and repeated playback.
- Default and custom filtering for HTTP, gRPC, and WebSocket data.
- Empty, JSON, text, binary, Unicode, gzip, deflate, Brotli, and Zstandard bodies.
- Every record mode with existing and missing cassette files.
- Empty `all` and `rewrite` runs.

## Format contract

A format case passes when an SDK parses its cassette into the corresponding canonical JSON value:

- Bodies are `{type, content}` with `type` set to `json`, `text`, `binary`, or `none`.
- A `none` body has no `content` key.
- Binary content is lowercase hexadecimal.
- Headers and metadata map each name to a list of values.
- Timestamps pass through without reformatting.
- Saving and reloading a cassette produces the same canonical value.
- Every case in `format/invalid/cases.json` fails to load.
- Unknown fields do not prevent known data from loading or round-tripping.
- Preservation of unknown fields is SDK-specific.

## SDK coverage

| SDK | Test |
|---|---|
| Python | `tests/test_conformance.py`, `tests/test_*_conformance.py` |
| Node | `ts/tests/*conformance.test.ts` |
| Go | `go/conformance_test.go`, `go/*_conformance_test.go` |

Each SDK reads the shared manifests. Add a case once and every implementation receives it.
The nested Go module includes a synchronized copy under `go/testdata/conformance/`.
This lets its tests run from a downloaded module without access to the repository parent.
Go CI fails when any copied fixture differs from this directory.

## Add a case

```console
$ rm -rf go/testdata/conformance
$ cp -R conformance go/testdata/conformance
$ uv run pytest tests/test_conformance.py tests/test_*_conformance.py
$ (cd ts && npm test -- --run tests/conformance.test.ts tests/behavior-conformance.test.ts tests/record-modes-conformance.test.ts)
$ (cd go && go test ./...)
```

Add the input and expected result to the appropriate directory.
Register the case in that directory's manifest when it has one.
Then synchronize the Go module copy and run every SDK test.

Generate expected output from an SDK, but do not trust one implementation alone.
Confirm all SDKs agree before committing it.
