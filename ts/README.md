# cassetter (Node)

HTTP cassette recorder for Node.js tests. Safe by default.

This is the Node binding. The cassette format, request matching, security
filtering, and body processing are implemented in Rust
([`crates/cassetter-core`](../crates/cassetter-core)) and shared with the Python
package, so cassettes are interchangeable between them.

## Install

```bash
npm install --save-dev cassetter
```

The package includes native addons for macOS and Windows on x64 and ARM64. It
also includes Linux x64 and ARM64 addons for glibc and musl.

## Quick start

```ts
import { useCassette } from "cassetter";

await useCassette("tests/cassettes/users.yaml", async () => {
  const res = await fetch("https://api.example.com/users");
  console.log(res.status); // 200
});
```

The first run records real traffic. Later runs replay from the file - no network.

With vitest:

```ts
import { expect, it } from "vitest";
import { useCassette } from "cassetter";

it("fetches users", async () => {
  await useCassette("tests/cassettes/users.yaml", async () => {
    const res = await fetch("https://api.example.com/users");
    expect(res.status).toBe(200);
  });
});
```

The callback receives the cassette if you want to inspect what was recorded:

```ts
await useCassette("cassette.yaml", async (cassette) => {
  await fetch("https://api.example.com/users");
  expect(cassette.interactions).toHaveLength(1);
});
```

## Record modes

| Mode | Behavior |
| --- | --- |
| `none` | Replay only. Throws `NoMatchError` if nothing matches. |
| `once` | Record if the cassette doesn't exist, otherwise replay. (default) |
| `new_episodes` | Replay what exists, record what doesn't. |
| `all` | Record everything, overwriting the cassette. |
| `rewrite` | Delete the cassette, then record everything. |

```ts
await useCassette("cassette.yaml", { recordMode: "none" }, async () => { ... });
```

Under `once`, an existing cassette replays only: an unmatched request throws
rather than silently reaching the network and appending to the file.

## Safe by default

Secrets are filtered **at write time**, so they never reach disk. The defaults
come from the Rust core - the same lists the Python package uses:

- **Headers**: `authorization`, `cookie`, `set-cookie`, `x-api-key`, `api-key`,
  `x-auth-token`, `proxy-authorization`, `www-authenticate`, `x-goog-api-key`,
  `x-amz-security-token`
- **Query params**: `api_key`, `apikey`, `token`, `access_token`, `client_secret`
- **JSON body fields**: `access_token`, `refresh_token`, `client_secret`, `password`

```ts
await useCassette("cassette.yaml", {
  filterHeaders: ["x-custom-secret"],
  bodyScrubPatterns: ["my_secret_field"],
  replacement: "***REDACTED***",
}, async () => { ... });
```

These **add to** the built-in lists rather than standing in for them, so naming
one more header to scrub never starts recording the ones above. Read the
built-ins with `defaultFilterHeaders()` and friends if you need them directly.

Filtering applies to every protocol: HTTP headers, query params, and bodies;
gRPC metadata and the `jsonDebug` payload; WebSocket handshake headers and
text/JSON frame bodies. Binary protobuf bodies are stored as-is - they cannot
be pattern-scrubbed.

## Request matching

Defaults to method + URI:

```ts
await useCassette("cassette.yaml", {
  matchOn: ["method", "uri", "json_body"],
  ignoreJsonPaths: ["requestId", "timestamp"],
}, async () => { ... });
```

Available matchers: `method`, `uri`, `headers`, `body`, `json_body`. An unknown
matcher is rejected rather than silently matching everything.

## Cassette format

YAML by default; use a `.toml` extension for TOML. TOML loads faster and
produces smaller files, but cannot store gRPC or WebSocket interactions.

```ts
await useCassette("cassette.toml", async () => { ... });
```

## Cassette expiry

```ts
await useCassette("cassette.yaml", {
  maxAge: "30d",
  onExpiry: "rerecord",
}, async () => { ... });
```

`maxAge` accepts `"24h"`, `"7d"`, `"4w"`. `onExpiry` is `warn` (default),
`fail`, or `rerecord`.

## Working with bodies

Bodies are `{ type, content }`, matching the cassette file. Binary content is
hex, so helpers are provided:

```ts
import { bodyToBuffer, binaryBody, binaryBodyBytes } from "cassetter";

bodyToBuffer({ type: "text", content: "hi" });
binaryBody(Buffer.from("hi"));
binaryBodyBytes({ type: "binary", content: "6869" });
```

## Interception

The global `fetch` is intercepted, which covers `fetch`, `undici`, and
libraries built on them. `ignoreLocalhost: true` lets localhost traffic through
untouched.

## Development

Requires a Rust toolchain and Node 18+.

```bash
npm install
npm run build:native   # compile the addon into native/
npm test
npm run typecheck
```

`npm run build` does the native build plus `tsc`.

Changes to matching, security, the cassette format, or body handling belong in
`crates/cassetter-core` so the Python binding gets them too - see
[`conformance/`](../conformance) for the suite that enforces this.
