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
| `new_episodes` | Replay unplayed interactions, record everything else. |
| `all` | Record everything, overwriting the cassette. |
| `rewrite` | Delete the cassette, then record everything. |
| `verify` | Send matched requests live and throw `ResponseMismatchError` if the response differs from the recording. |

A session that can record only replays interactions it hasn't played yet, and never replays one it just recorded. A repeated request, like the next turn of a conversation posting to the same URL, reaches the server instead of getting an earlier response back.

```ts
await useCassette("cassette.yaml", { recordMode: "none" }, async () => { ... });
```

Under `once`, an existing cassette replays only: an unmatched request throws
rather than silently reaching the network and appending to the file.

### `verify`

Use it when the cassette is the expected output of the service under test, not a stand-in for a
dependency. For example, when you port an HTTP API: record the reference implementation once, then
check the new one against it.

```ts
import { useCassette, type UseCassetteOptions } from "cassetter";

const options: UseCassetteOptions = {
  matchOn: ["method", "uri", "body"],
  compare: {
    headers: ["content-type", "x-price-*"],
    jsonIgnore: ["id", "created"],
    floatTolerance: 1e-9,
  },
};
const chat = () =>
  fetch("http://localhost:8000/v1/chat", { method: "POST", body: JSON.stringify({ messages: [] }) });

// Against the reference implementation.
await useCassette("tests/expected/chat.yaml", { ...options, recordMode: "rewrite" }, chat);

// Against the new implementation.
await useCassette("tests/expected/chat.yaml", { ...options, recordMode: "verify" }, chat);
```

Matching works as in `none`: `matchOn` picks the recording, and a request without one throws
`NoMatchError`. After a match, the request goes to the network, the response is decompressed and
scrubbed as a recording would be, and compared to the recorded one. The cassette is never written.

`compare` decides what counts as equivalent:

| Field | Compared |
| --- | --- |
| status | Always, exactly. |
| `headers` | Only the listed names, by value. Globs such as `x-price-*` are allowed. Every other header is ignored. |
| `jsonIgnore` | JSON bodies are compared structurally, without these paths. Same syntax as `ignoreJsonPaths`. |
| `floatTolerance` | Largest difference between two JSON numbers that still counts as equal. |
| `sse` | Compare the body as its Server-Sent Events `data:` payloads, so chunk boundaries and comments do not matter. JSON payloads are parsed, and `jsonIgnore` applies to each. |

Any other body is compared as text. On a difference, the request fails with a `ResponseMismatchError`
whose message is a unified diff of both responses, as compared:

```
cassette tests/expected/chat.yaml, POST http://localhost:8000/v1/chat
--- recorded
+++ live
@@ -1,7 +1,7 @@
 status: 200
 @@ headers @@
 content-type: application/json
-x-price-estimate: 0.0001USD
+x-price-estimate: 0.0002USD
 @@ json body @@
 {
   "content": "hi"
```

For differences `compare` cannot express, `beforeCompareResponse` receives the recorded and the live
`HttpResponse` and returns both, normalized:

```ts
import type { HttpResponse } from "cassetter";

const dropNulls = (response: HttpResponse): HttpResponse => ({
  ...response,
  body: {
    type: "json",
    content: Object.fromEntries(
      Object.entries(response.body.content as object).filter(([, value]) => value !== null),
    ),
  },
});

const beforeCompareResponse = (recorded: HttpResponse, live: HttpResponse) =>
  [dropNulls(recorded), dropNulls(live)] as [HttpResponse, HttpResponse];

await useCassette("tests/expected/chat.yaml", { recordMode: "verify", beforeCompareResponse }, chat);
```

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
A header entry may use `*` to match any run of characters, and one starting
with `!` keeps the headers it matches: `["x-*", "!x-amzn-bedrock-*"]` drops
every `x-` header except Bedrock's.

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

Two interceptors are installed by default:

| Name | Patches | Covers |
| --- | --- | --- |
| `fetch` | the global `fetch` | `fetch` and libraries built on it |
| `http` | `request` and `get` on `node:http` and `node:https` | `node-fetch`, `axios`, `gaxios` and the Google Cloud clients |

Pass `intercept` to install only some of them:

```ts
await useCassette("cassette.yaml", { intercept: ["fetch"] }, async () => { ... });
```

`ignoreLocalhost: true` lets localhost traffic through untouched. `CONNECT`,
upgrade, and `Expect: 100-continue` requests always go live, since they trade data
before or instead of a response.

> [!NOTE]
> The `http` interceptor swaps the functions on the module. Code that saved
> `http.request` into a variable before the cassette started keeps the original.

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
