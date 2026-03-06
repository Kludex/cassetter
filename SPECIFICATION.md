# cassetter - Specification

This document describes the design decisions behind cassetter. Each section explains what was chosen, what alternatives were considered, and why.

## 1. Cassette format (v1)

### 1.1. Structured JSON bodies

JSON request/response bodies are stored as structured YAML, not as escaped strings.

```yaml
# cassetter
body:
  type: json
  content:
    model: gpt-4o
    messages:
      - role: user
        content: Hello!

# VCR.py
body: '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello!"}]}'
```

**Alternatives considered:**

- **Escaped string (VCR.py approach).** Unreadable in diffs, hard to manually edit, causes noisy git diffs when only formatting changes. Rejected because human readability is a primary goal.

- **Separate JSON files per body.** Each body stored as a `.json` sidecar file. Would be cleaner for large payloads but fragments cassettes across many files, makes atomic operations harder, and complicates the matching engine. Rejected because the complexity isn't justified - structured YAML is readable enough.

**Why this choice:** Most cassettes are for JSON APIs. Storing JSON as structured YAML makes diffs clean, cassettes editable, and bodies inspectable without tooling.

### 1.2. Typed body field

Bodies have an explicit `type` discriminator: `json`, `text`, `binary`, or `none`.

```yaml
body:
  type: json
  content: { ... }
```

**Alternatives considered:**

- **Infer type from content-type header.** Less explicit, breaks when headers are stripped by filtering, and requires the matching engine to re-infer types at match time. Rejected because explicit typing is more reliable.

- **Flat field like VCR.py's `parsed_body`.** VCR.py (via pydantic-ai's custom serializer) uses `parsed_body` as a peer field to `headers`/`method`/`uri`. This mixes concerns - the body representation bleeds into the request/response structure. Our `body: { type, content }` keeps it contained. Rejected because it's less structured.

**Why this choice:** Explicit typing makes the format self-describing. A reader doesn't need to guess whether the content is JSON, plain text, or binary.

### 1.3. Status code as integer

Response status is stored as a plain integer, not a `{ code, message }` object.

```yaml
# cassetter
status: 200

# VCR.py
status:
  code: 200
  message: OK
```

**Alternatives considered:**

- **`{ code, message }` object (VCR.py approach).** The status message is derivable from the code and adds no information. It's extra noise in the YAML. Rejected because it's redundant.

**Why this choice:** Status messages are standardized (RFC 9110). Storing them adds bytes without information. The integer is cleaner and sufficient.

### 1.4. Optional `recorded_at` timestamp

Each interaction has an optional `recorded_at` ISO 8601 timestamp.

**Alternatives considered:**

- **Required timestamp.** Would complicate migration from other formats and add noise to manually-created cassettes. Rejected because it's not always useful.

- **No timestamp at all.** Timestamps help when debugging stale cassettes or understanding when a recording was made. Keeping it optional preserves this information without mandating it. Rejected because the information can be valuable.

**Why this choice:** Optional gives the best of both worlds - available when useful, not in the way when not.

## 2. Interception

Each library is intercepted at the highest-level extension point available:

| Library | Protocol | Method |
|---------|----------|--------|
| httpx | HTTP | `AsyncBaseTransport` / `BaseTransport` wrapping |
| aiohttp | HTTP | Session `_request` patch |
| requests | HTTP | Session `send` patch |
| urllib3 | HTTP | `HTTPConnectionPool.urlopen` patch |
| grpcio | gRPC | `grpc.aio.Channel` wrapper |
| websockets | WebSocket | `websockets.connect` patch |

httpx is the only library with a proper transport API. The rest require monkey-patching at the session or connection level - the same general approach as VCR.py, but patching at a higher layer where possible.

**Alternatives considered:**

- **Monkey-patching socket/ssl modules (VCR.py approach).** VCR.py patches `http.client`, `urllib3`, and low-level socket internals. Patching at a higher layer (session/transport) is more resilient to internal refactors, though still not immune. Accepted as a pragmatic middle ground.

- **Proxy server.** Run a local HTTP proxy that records traffic. Works for any library without per-library integration. But adds network hops (slower), requires configuring each client to use the proxy, doesn't work well with TLS, and is harder to set up in CI. Rejected because the integration overhead outweighs the generality benefit.

**Why this choice:** Per-library integration at the session/transport layer is more stable than low-level socket patching while avoiding the complexity of a proxy. The tradeoff is needing per-library code, but auto-detection handles this transparently.

## 3. Security: Safe by default

Sensitive data is filtered at write time. Cassettes never contain secrets. This is opt-out, not opt-in.

**Default filtered headers:** `authorization`, `cookie`, `set-cookie`, `x-api-key`, `api-key`, `x-auth-token`, `proxy-authorization`, `www-authenticate`

**Default filtered query params:** `api_key`, `apikey`, `token`, `access_token`, `client_secret`

**Default body scrub patterns:** `access_token`, `refresh_token`, `client_secret`, `password`

**Alternatives considered:**

- **Filter at read time (VCR.py approach).** VCR.py stores everything and filters on playback. This means cassette files committed to git contain API keys, tokens, and passwords. Once committed, secrets are in git history forever. Rejected because it's a security anti-pattern.

- **No default filtering.** Let users configure everything. Most users won't bother, and secrets will leak. Rejected because safe defaults prevent the most common mistake.

- **Environment variable detection.** Auto-detect values that match environment variables and filter them. Clever but fragile - doesn't catch secrets from config files, key vaults, or hardcoded test values. Also adds runtime overhead scanning all values. Rejected because it's unreliable.

**Why this choice:** Write-time filtering means secrets never touch disk. The defaults cover the most common patterns (HTTP auth, OAuth tokens, API keys). Users can add custom patterns or disable filtering entirely if needed.

## 4. Request matching

Default matching is on method + URI. Configurable to include headers, body, or JSON body (with path ignoring).

**Alternatives considered:**

- **Match on everything by default.** Too strict - minor header changes (user-agent version, date) would break playback. Rejected because it creates brittle tests.

- **Fuzzy matching.** Score-based matching that picks the "best" match. Hard to reason about, unpredictable, and can silently return wrong responses when cassettes are stale. Rejected because predictability matters more than flexibility.

- **Sequential matching (VCR.py's default).** Return interactions in order regardless of request content. Simple but breaks when test execution order changes or when tests make requests in different orders on retry. Rejected because it couples tests to request ordering.

**Why this choice:** Method + URI matching is predictable and sufficient for most API tests. JSON body matching with path ignoring handles the common case of timestamp/request-ID fields that change between runs.

## 5. Body processing

### 5.1. Auto-decompression

Response bodies are decompressed (gzip, brotli, zstd) before storage. The `content-encoding` header is removed from stored responses.

**Alternatives considered:**

- **Store compressed (VCR.py approach).** VCR.py stores compressed bodies and relies on `decode_compressed_response: True` in config. This causes a double-decompression bug: the HTTP client decompresses on replay, then VCR.py also decompresses, corrupting the body. Rejected because it's a known source of bugs.

- **Store both compressed and decompressed.** Wastes space and creates format ambiguity. Rejected because decompression is lossless - we can always re-compress if needed.

**Why this choice:** Decompressing at write time makes cassettes human-readable, prevents double-decompression bugs, and reduces file size (YAML compresses differently than gzip).

### 5.2. Unicode normalization

Text response bodies are NFC-normalized before storage.

**Alternatives considered:**

- **Store raw Unicode.** Different Unicode representations of the same text (e.g., composed vs decomposed characters) cause spurious cassette diffs. NFC normalization makes recordings stable. Rejected because it creates unnecessary maintenance work.

- **ASCII normalization (smart quotes to ASCII).** An earlier version also replaced smart quotes (`\u201c`/`\u201d`) with ASCII `"`. This corrupted JSON embedded in text bodies (e.g., SSE streams) because curly quotes are valid unescaped in JSON while ASCII `"` is not. Rejected and removed.

**Why this choice:** NFC normalization stabilizes Unicode representation without altering content semantics. It prevents spurious diffs while preserving the original characters.

## 6. Pytest integration

### 6.1. Auto-fixture injection

Tests marked with `@pytest.mark.vcr` automatically get the `cassette` fixture without declaring it as a parameter.

```python
@pytest.mark.vcr
async def test_api():  # No need for `cassette` param
    ...
```

This is implemented via `pytest_collection_modifyitems` adding `cassette` to `fixturenames`.

**Alternatives considered:**

- **Require explicit fixture parameter (our initial approach).** More explicit, but adds noise to every VCR test. In pydantic-ai's test suite, most tests don't need to interact with the cassette directly - they just need recording/playback to happen. Rejected because it adds boilerplate.

- **Autouse fixture on all tests.** Too broad - would affect tests that don't need VCR. Rejected because it violates the principle of least surprise.

**Why this choice:** Matches pytest-recording's behavior, which pydantic-ai and many other projects already use. Tests that need direct cassette access can still declare the parameter.

### 6.2. Cassette path resolution

Cassettes are stored at `{test_dir}/cassettes/{test_file_stem}/{test_name}.yaml`.

```
tests/
  models/
    test_openai.py
    cassettes/
      test_openai/
        test_simple_chat.yaml
        test_streaming.yaml
```

**Alternatives considered:**

- **Flat directory.** All cassettes in one `cassettes/` dir. Name collisions between test files (e.g., `test_simple` in two different modules). Rejected because it doesn't scale.

- **Mirror full test path.** Store cassettes mirroring the full test module path. Over-nested for most projects. Rejected because the test file stem provides sufficient namespacing.

**Why this choice:** Matches pytest-recording's convention, which many projects already follow. One subdirectory per test module keeps things organized without deep nesting.

### 6.3. Graceful missing cassettes

When `record_mode=none` and a cassette file doesn't exist, the fixture creates an empty in-memory cassette instead of raising an error. If no interactions are recorded, nothing is saved to disk.

**Alternatives considered:**

- **Raise error on missing cassette (our initial approach).** Breaks tests that use module-level `pytestmark = [pytest.mark.vcr]` where many tests use mock clients and never make HTTP requests. These tests have no cassettes and don't need them. Rejected because it breaks a common pattern.

**Why this choice:** Module-level VCR markers are convenient for test files where most-but-not-all tests need recording. Non-recording tests shouldn't be forced to have empty cassette files.

## 7. Scope and non-goals

### Implemented
- HTTP recording/replay for httpx, aiohttp, requests, urllib3
- gRPC message recording via grpcio
- WebSocket frame recording via websockets
- Structured YAML cassette format with typed bodies
- Safe-by-default security filtering
- Configurable request matching
- Auto-decompression and Unicode normalization
- Cassette TTL/expiration (`max_age`)
- Pytest plugin with markers, fixtures, and orphan detection

### Future
- VCR.py cassette migration tool
- Cassette semantic diffing

### Non-goals
- Proxy mode for recording (adds complexity without clear benefit over transport interception)
