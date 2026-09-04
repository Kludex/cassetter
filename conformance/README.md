# Cross-language conformance

Every cassetter SDK must read and write the same cassette data.
The shared fixtures in this directory are the contract between implementations.

## Fixture sets

| Directory | Purpose |
|---|---|
| `format/` | Cassette parsing and save-and-reload compatibility. |

Each fixture set contains a `cases.json` manifest.
Every case names an input cassette and its canonical JSON representation.

The format fixtures cover:

- Every body type.
- Multi-value headers and metadata.
- Unicode text and nested JSON.
- HTTP, gRPC, and WebSocket interactions.
- Empty cassettes.

Additional sets will cover invalid cassettes, request matching, filtering, body processing, and record modes.

## Format contract

A format case passes when an SDK parses its cassette into the corresponding canonical JSON value:

- Bodies are `{type, content}` with `type` set to `json`, `text`, `binary`, or `none`.
- A `none` body has no `content` key.
- Binary content is lowercase hexadecimal.
- Headers and metadata map each name to a list of values.
- Timestamps pass through without reformatting.
- Saving and reloading a cassette produces the same canonical value.

## SDK coverage

| SDK | Test |
|---|---|
| Python | `tests/test_conformance.py` |
| Node | `ts/tests/conformance.test.ts` |
| Go | `go/conformance_test.go` |

Each SDK reads `cases.json`. Add a case once and every implementation receives it.
The nested Go module includes a synchronized copy under `go/testdata/conformance/`.
This lets its tests run from a downloaded module without access to the repository parent.
Go CI fails when that copy differs from this directory.

## Adding a format case

1. Add the cassette under `format/`.
2. Add its canonical JSON representation beside it.
3. Register both files in `format/cases.json`.
4. Run the Python, Node, and Go conformance tests.

Generate canonical output from an SDK, but do not trust one implementation alone.
Confirm all SDKs agree before committing a changed expected file.
