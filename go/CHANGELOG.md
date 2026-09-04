# Changelog

## 0.1.0 - 2026-09-04

This is the first release of the Go SDK.

### Recording and replay

- Added streaming HTTP recording and replay through `http.RoundTripper` with atomic cassette writes and safe default
  filtering ([#96](https://github.com/Kludex/cassetter/pull/96)).
- Added deterministic test cleanup, incomplete body detection, and save error reporting
  ([#100](https://github.com/Kludex/cassetter/pull/100)).
- Added configurable HTTP request matching, ignored JSON paths, URI normalization, and repeated playback
  ([#101](https://github.com/Kludex/cassetter/pull/101)).
- Added expiry policies, host bypass, request and response hooks, and Unicode NFC normalization
  ([#102](https://github.com/Kludex/cassetter/pull/102)).
- Added unary and streaming gRPC client interceptors with metadata, status, cancellation, and protobuf support
  ([#105](https://github.com/Kludex/cassetter/pull/105)).
- Added WebSocket text, binary, close status, subprotocol, filtering, and lifecycle support through `coder/websocket`
  ([#106](https://github.com/Kludex/cassetter/pull/106)).

### Formats and tooling

- Added typed HTTP, gRPC, and WebSocket cassette structures shared with Python and Node
  ([#99](https://github.com/Kludex/cassetter/pull/99)).
- Added TOML support, YAML and TOML conversion, and VCR.py migration
  ([#103](https://github.com/Kludex/cassetter/pull/103)).
- Added `inspect`, `diff`, `scrub`, and `convert` commands for cassette maintenance
  ([#96](https://github.com/Kludex/cassetter/pull/96), [#103](https://github.com/Kludex/cassetter/pull/103)).
- Added shared format and behavior conformance fixtures run by Go, Python, and Node
  ([#104](https://github.com/Kludex/cassetter/pull/104)).
