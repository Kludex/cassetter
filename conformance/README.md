# Cross-language conformance

Every cassetter binding shares one implementation (`crates/cassetter-core`), but
each one still has a thin layer that converts between core types and its host
language. This directory is the contract that layer must satisfy.

## Files

| File | Purpose |
|------|---------|
| `cassette.yaml` | A cassette exercising every body type, multi-value headers, unicode, nested JSON, and all three protocols. |
| `expected.json` | The canonical structure that parsing `cassette.yaml` must produce, in a language-neutral shape. |

## The contract

A binding conforms when, given `cassette.yaml`, it can produce `expected.json`:

- Bodies are `{type, content}` with `type` one of `json`, `text`, `binary`, `none`.
- A `none` body has no `content` key.
- Binary content is lowercase hex.
- Headers and metadata are maps of name to a **list** of values, even when there is one value.
- Timestamps are passed through verbatim; bindings do not reformat them.
- Saving a parsed cassette and re-parsing it must yield the same structure.

## Who runs it

| Binding | Test |
|---------|------|
| Python | `tests/test_conformance.py` |
| Node | `ts/tests/conformance.test.ts` |

Both assert against the same `expected.json`, so a change that makes one binding
disagree with the other fails CI.

## Adding a language

1. Write the thin binding crate under `crates/`.
2. Port the canonicalizer from either existing test - it is ~40 lines.
3. Assert it equals `expected.json`, plus the save/reload round-trip.

If those pass, the new binding reads and writes cassettes interchangeably with
every other one.

## Changing the fixture

`expected.json` is generated, not hand-edited. Regenerate it from a binding and
confirm the other binding still agrees before committing - if the two disagree,
that is the drift this suite exists to catch.
