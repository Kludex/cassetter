import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import {
  createServer,
  get as httpGet,
  request as httpRequest,
  type IncomingHttpHeaders,
  type IncomingMessage,
  type RequestOptions,
  type Server,
} from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { once } from "node:events";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync, gzipSync } from "node:zlib";

import { BigQuery } from "@google-cloud/bigquery";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Cassette, NoMatchError } from "../src/cassette.js";
import { FetchInterceptor } from "../src/intercept/fetch.js";
import { RecordMode } from "../src/recording.js";
import { ResponseMismatchError } from "../src/compare.js";
import { useCassette, type UseCassetteOptions } from "../src/context.js";
import type { HttpResponse } from "../src/types.js";

let dir: string;
let realFetch: typeof globalThis.fetch;

beforeEach(() => {
  dir = join(tmpdir(), `cassetter-ctx-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  mkdirSync(dir, { recursive: true });
  realFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  rmSync(dir, { recursive: true, force: true });
});

/** Stand in for the network so tests never make real requests. */
function stubUpstream(handler: (req: Request) => Response): void {
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) =>
    handler(new Request(input, init))) as typeof globalThis.fetch;
}

describe("useCassette", () => {
  it("records on first run and replays on the second", async () => {
    const path = join(dir, "rec.yaml");
    let upstreamCalls = 0;

    stubUpstream(() => {
      upstreamCalls += 1;
      return new Response(JSON.stringify({ users: ["ada"] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });

    await useCassette(path, async () => {
      const res = await fetch("https://api.example.com/users");
      expect(res.status).toBe(200);
      await expect(res.json()).resolves.toEqual({ users: ["ada"] });
    });

    expect(upstreamCalls).toBe(1);
    expect(readFileSync(path, "utf-8")).toContain("uri: https://api.example.com/users");

    // Second run replays; upstream must not be touched again.
    await useCassette(path, { recordMode: "none" }, async () => {
      const res = await fetch("https://api.example.com/users");
      expect(res.status).toBe(200);
      await expect(res.json()).resolves.toEqual({ users: ["ada"] });
    });

    expect(upstreamCalls).toBe(1);
  });

  it("restores the original fetch afterwards", async () => {
    stubUpstream(() => new Response("{}", { status: 200 }));
    const before = globalThis.fetch;

    await useCassette(join(dir, "x.yaml"), { recordMode: "none" }, async () => {
      expect(globalThis.fetch).not.toBe(before);
    });

    expect(globalThis.fetch).toBe(before);
  });

  it("restores fetch even when the callback throws", async () => {
    stubUpstream(() => new Response("{}", { status: 200 }));
    const before = globalThis.fetch;

    await expect(
      useCassette(join(dir, "x.yaml"), { recordMode: "none" }, async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");

    expect(globalThis.fetch).toBe(before);
  });

  it("raises NoMatchError in none mode with no cassette", async () => {
    stubUpstream(() => new Response("{}", { status: 200 }));

    await expect(
      useCassette(join(dir, "none.yaml"), { recordMode: "none" }, async () => {
        await fetch("https://api.example.com/nope");
      }),
    ).rejects.toThrow(NoMatchError);
  });

  it("scrubs secrets before they reach disk", async () => {
    const path = join(dir, "secret.yaml");
    stubUpstream(
      () =>
        new Response(JSON.stringify({ access_token: "tok-live" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );

    await useCassette(path, async () => {
      await fetch("https://api.example.com/oauth?api_key=live-key", {
        method: "POST",
        headers: {
          authorization: "Bearer live-token",
          "content-type": "application/json",
        },
        body: JSON.stringify({ password: "hunter2" }),
      });
    });

    const yaml = readFileSync(path, "utf-8");
    expect(yaml).not.toContain("live-token");
    expect(yaml).not.toContain("live-key");
    expect(yaml).not.toContain("hunter2");
    expect(yaml).not.toContain("tok-live");
    expect(yaml).toContain("[FILTERED]");
  });

  it("records the request body", async () => {
    const path = join(dir, "body.yaml");
    stubUpstream(() => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));

    const cassette = await useCassette(path, async () => {
      await fetch("https://api.example.com/echo", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ hello: "world" }),
      });
    });

    expect(cassette.interactions[0].request.body.content).toEqual({
      hello: "world",
    });
  });

  it("passes the cassette to the callback", async () => {
    stubUpstream(() => new Response("{}", { status: 200 }));
    const returned = await useCassette(
      join(dir, "cb.yaml"),
      { recordMode: "none" },
      async (cassette) => {
        expect(cassette.interactions).toEqual([]);
      },
    );
    expect(returned.interactions).toEqual([]);
  });

  it("rejects an unknown interceptor", async () => {
    await expect(
      useCassette(join(dir, "x.yaml"), { intercept: ["nope"] }, async () => {}),
    ).rejects.toThrow(/unknown interceptor/);
  });

  it("bypasses the cassette for localhost when configured", async () => {
    let hits = 0;
    stubUpstream(() => {
      hits += 1;
      return new Response("local", { status: 200 });
    });

    await useCassette(
      join(dir, "local.yaml"),
      { recordMode: "none", ignoreLocalhost: true },
      async () => {
        const res = await fetch("http://localhost:8080/health");
        expect(res.status).toBe(200);
      },
    );

    expect(hits).toBe(1);
  });
});

describe("useCassette options", () => {
  it("adds custom filters to the defaults rather than replacing them", async () => {
    const path = join(dir, "filters.yaml");
    stubUpstream(
      () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );

    await useCassette(
      path,
      { filterHeaders: ["x-tenant"], bodyScrubPatterns: ["ssn"] },
      async () => {
        await fetch("https://api.example.com/x", {
          method: "POST",
          headers: {
            authorization: "Bearer built-in-secret",
            "x-tenant": "custom-secret",
            "content-type": "application/json",
          },
          body: JSON.stringify({ ssn: "custom-body", password: "built-in-body" }),
        });
      },
    );

    const yaml = readFileSync(path, "utf-8");
    // The custom entries are scrubbed...
    expect(yaml).not.toContain("custom-secret");
    expect(yaml).not.toContain("custom-body");
    // ...and naming them did not stop the built-ins being scrubbed.
    expect(yaml).not.toContain("built-in-secret");
    expect(yaml).not.toContain("built-in-body");
  });

  it.each(["all", "rewrite"] as const)(
    "%s records every identical request",
    async (recordMode) => {
      const path = join(dir, `${recordMode}.yaml`);
      let upstreamCalls = 0;
      stubUpstream(() => {
        upstreamCalls += 1;
        return new Response(JSON.stringify({ call: upstreamCalls }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      });

      const cassette = await useCassette(path, { recordMode }, async () => {
        await fetch("https://api.example.com/same");
        await fetch("https://api.example.com/same");
      });

      expect(upstreamCalls).toBe(2);
      expect(cassette.interactions).toHaveLength(2);
    },
  );

  it("rewrite re-records over an existing cassette", async () => {
    const path = join(dir, "rw.yaml");
    stubUpstream(
      () =>
        new Response(JSON.stringify({ generation: 1 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    await useCassette(path, async () => {
      await fetch("https://api.example.com/gen");
    });
    expect(readFileSync(path, "utf-8")).toContain("generation");

    stubUpstream(
      () =>
        new Response(JSON.stringify({ generation: 2 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const cassette = await useCassette(
      path,
      { recordMode: "rewrite" },
      async () => {
        await fetch("https://api.example.com/gen");
      },
    );

    expect(cassette.interactions).toHaveLength(1);
    expect(cassette.interactions[0].response.body.content).toEqual({
      generation: 2,
    });
  });

  it("once refuses to record over an existing cassette", async () => {
    const path = join(dir, "once.yaml");
    stubUpstream(() => new Response("{}", { status: 200 }));
    await useCassette(path, async () => {
      await fetch("https://api.example.com/a");
    });

    // The cassette now exists, so an unmatched request must raise rather than
    // silently hitting the network and appending.
    await expect(
      useCassette(path, async () => {
        await fetch("https://api.example.com/unmatched");
      }),
    ).rejects.toThrow(NoMatchError);
  });
});

describe("response decoding", () => {
  it("records a response whose content-encoding header outlived the decoding", async () => {
    const path = join(dir, "gz.yaml");
    const payload = JSON.stringify({ compressed: false });

    // What Node's fetch hands back: bytes already decoded, upstream
    // content-encoding still on the response.
    stubUpstream(
      () =>
        new Response(payload, {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-encoding": "gzip",
          },
        }),
    );

    const cassette = await useCassette(path, async () => {
      const res = await fetch("https://api.example.com/gz");
      expect(res.status).toBe(200);
    });

    const rec = cassette.interactions[0];
    expect(rec.response.body.content).toEqual({ compressed: false });
    expect(rec.response.headers["content-encoding"]).toBeUndefined();
    expect(rec.response.headers["content-length"]).toBeUndefined();
  });
});

describe("overlapping scopes", () => {
  function scope(name: string) {
    const cassette = new Cassette(join(dir, name), { recordMode: RecordMode.ALL });
    cassette.load();
    return cassette;
  }

  it("does not take the global back from a scope that is still live", () => {
    stubUpstream(() => new Response("{}", { status: 200 }));
    const outer = new FetchInterceptor();
    const inner = new FetchInterceptor();
    const cassette = scope("a.yaml");

    outer.install(cassette);
    inner.install(cassette);
    const innerPatched = globalThis.fetch;

    // Out-of-order teardown: the outer scope finishes first. Restoring
    // unconditionally would drop the inner interceptor, which is still live.
    outer.uninstall();
    expect(globalThis.fetch).toBe(innerPatched);

    inner.uninstall();
  });

  it("restores the original fetch after out-of-order teardown", () => {
    stubUpstream(() => new Response("{}", { status: 200 }));
    const original = globalThis.fetch;
    const outer = new FetchInterceptor();
    const inner = new FetchInterceptor();
    const cassette = scope("identity.yaml");

    outer.install(cassette);
    inner.install(cassette);
    outer.uninstall();
    inner.uninstall();

    expect(globalThis.fetch).toBe(original);
  });

  it("stops intercepting once every scope has ended", async () => {
    let upstream = 0;
    stubUpstream(() => {
      upstream += 1;
      return new Response("{}", { status: 200 });
    });
    const original = globalThis.fetch;

    const outer = new FetchInterceptor();
    const inner = new FetchInterceptor();
    const cassette = scope("b.yaml");

    outer.install(cassette);
    inner.install(cassette);
    outer.uninstall();
    inner.uninstall();

    await fetch("https://api.example.com/after");

    expect(globalThis.fetch).toBe(original);
    expect(upstream).toBe(1);
    expect(cassette.interactions).toHaveLength(0);
  });
});

describe("node:http", () => {
  let server: Server;
  let origin: string;
  let hits: number;
  let release: () => void;

  beforeEach(async () => {
    hits = 0;
    server = createServer(async (req, res) => {
      hits += 1;
      if (req.url === "/stall") return;
      if (req.url === "/stream") {
        res.writeHead(200, { "content-type": "text/plain" });
        res.write("first ");
        release = () => res.end("last");
        return;
      }
      const chunks: Buffer[] = [];
      for await (const chunk of req) chunks.push(chunk as Buffer);
      res.writeHead(200, {
        "content-type": "application/json",
        "content-encoding": "gzip",
        "x-hit": String(hits),
      });
      res.end(
        gzipSync(
          JSON.stringify({ method: req.method, url: req.url, body: Buffer.concat(chunks).toString() }),
        ),
      );
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterEach(() => {
    server.close();
  });

  function send(
    url: string,
    options: RequestOptions = {},
    body?: string,
  ): Promise<{ status: number; headers: IncomingHttpHeaders; body: string }> {
    return new Promise((resolve, reject) => {
      const req = httpRequest(url, options, async (res) => {
        const chunks: Buffer[] = [];
        for await (const chunk of res) chunks.push(chunk as Buffer);
        const raw = Buffer.concat(chunks);
        const decoded = res.headers["content-encoding"] === "gzip" ? gunzipSync(raw) : raw;
        resolve({ status: res.statusCode!, headers: res.headers, body: decoded.toString() });
      });
      req.on("error", reject);
      req.end(body);
    });
  }

  it("records on first run and replays on the second", async () => {
    const path = join(dir, "http.yaml");
    const expected = { method: "POST", url: "/echo?q=1", body: '{"hello":"world"}' };

    const cassette = await useCassette(path, async () => {
      const res = await send(
        `${origin}/echo?q=1`,
        { method: "POST", headers: { "content-type": "application/json" } },
        JSON.stringify({ hello: "world" }),
      );
      expect(res.status).toBe(200);
      expect(JSON.parse(res.body)).toEqual(expected);
    });

    expect(hits).toBe(1);
    const rec = cassette.interactions[0];
    expect(rec.request.uri).toBe(`${origin}/echo?q=1`);
    expect(rec.request.body.content).toEqual({ hello: "world" });
    expect(rec.response.body.content).toEqual(expected);

    await useCassette(path, { recordMode: "none" }, async () => {
      const res = await send(
        `${origin}/echo?q=1`,
        { method: "POST", headers: { "content-type": "application/json" } },
        JSON.stringify({ hello: "world" }),
      );
      expect(res.status).toBe(200);
      expect(res.headers["x-hit"]).toBe("1");
      expect(JSON.parse(res.body)).toEqual(expected);
    });

    expect(hits).toBe(1);
  });

  it("intercepts http.get with an options object", async () => {
    const { hostname, port } = new URL(origin);
    const cassette = await useCassette(join(dir, "get.yaml"), async () => {
      const status = await new Promise<number>((resolve, reject) => {
        httpGet({ hostname, port, path: "/thing" }, (res) => {
          res.resume();
          res.on("end", () => resolve(res.statusCode!));
        }).on("error", reject);
      });
      expect(status).toBe(200);
    });

    expect(cassette.interactions[0].request.uri).toBe(`${origin}/thing`);
  });

  it("emits NoMatchError on the request in none mode", async () => {
    await expect(
      useCassette(join(dir, "none.yaml"), { recordMode: "none" }, () => send(`${origin}/nope`)),
    ).rejects.toThrow(NoMatchError);
    expect(hits).toBe(0);
  });

  it("bypasses the cassette for localhost when configured", async () => {
    const cassette = await useCassette(
      join(dir, "local.yaml"),
      { recordMode: "none", ignoreLocalhost: true },
      () => send(`${origin}/health`),
    );
    expect(hits).toBe(1);
    expect(cassette.interactions).toHaveLength(0);
  });

  it("stops intercepting after the scope ends", async () => {
    const before = httpRequest;
    const cassette = await useCassette(join(dir, "after.yaml"), async () => {
      expect(httpRequest).not.toBe(before);
    });
    expect(httpRequest).toBe(before);

    await send(`${origin}/after`);
    expect(hits).toBe(1);
    expect(cassette.interactions).toHaveLength(0);
  });

  it("hands the live response over before its body ends", async () => {
    const cassette = await useCassette(join(dir, "stream.yaml"), async () => {
      const res = await new Promise<IncomingMessage>((resolve, reject) =>
        httpGet(`${origin}/stream`, resolve).on("error", reject),
      );
      const [first] = (await once(res, "data")) as [Buffer];
      expect(first.toString()).toBe("first ");
      release();
      let rest = "";
      for await (const chunk of res) rest += chunk;
      expect(rest).toBe("last");
    });

    expect(cassette.interactions[0].response.body.content).toBe("first last");
  });

  it("applies setTimeout to the live request", async () => {
    await useCassette(join(dir, "timeout.yaml"), async () => {
      const req = httpGet(`${origin}/stall`);
      req.on("error", () => {});
      await new Promise<void>((resolve) => req.setTimeout(50, resolve));
      req.destroy();
    });
    expect(hits).toBe(1);
  });

  it("reads headers given as a flat array", async () => {
    const cassette = await useCassette(join(dir, "raw.yaml"), () =>
      send(`${origin}/raw`, { headers: ["X-Tag", "a", "X-Tag", "b", "Accept", "text/plain"] }),
    );
    const { headers } = cassette.interactions[0].request;
    expect(headers["x-tag"]).toEqual(["a", "b"]);
    expect(headers.accept).toEqual(["text/plain"]);
  });

  it("records a fetch built on node:http once", async () => {
    globalThis.fetch = (async (input: string | URL | Request) => {
      const res = await send(String(input instanceof Request ? input.url : input));
      return new Response(res.body, { status: res.status });
    }) as typeof globalThis.fetch;

    const cassette = await useCassette(join(dir, "polyfill.yaml"), async () => {
      await fetch(`${origin}/polyfill`);
    });

    expect(hits).toBe(1);
    expect(cassette.interactions).toHaveLength(1);
  });

  it("records a nested scope's request only in the inner cassette", async () => {
    const outer = await useCassette(join(dir, "outer.yaml"), { recordMode: "none" }, async () => {
      const inner = await useCassette(join(dir, "inner.yaml"), () => send(`${origin}/nested`));
      expect(inner.interactions).toHaveLength(1);
    });
    expect(outer.interactions).toHaveLength(0);
    expect(hits).toBe(1);
  });

  it("aborts a replayed request through its signal", async () => {
    const path = join(dir, "signal.yaml");
    await useCassette(path, () => send(`${origin}/signal`));

    await useCassette(path, { recordMode: "none" }, async () => {
      const controller = new AbortController();
      const result = send(`${origin}/signal`, { signal: controller.signal });
      controller.abort();
      await expect(result).rejects.toMatchObject({ name: "AbortError" });
    });
  });

  it("sends Expect: 100-continue requests live", async () => {
    const cassette = await useCassette(join(dir, "expect.yaml"), { recordMode: "none" }, async () => {
      const status = await new Promise<number>((resolve, reject) => {
        const req = httpRequest(`${origin}/expect`, { method: "POST", headers: { expect: "100-continue" } }, (res) => {
          res.resume();
          resolve(res.statusCode!);
        });
        req.on("error", reject);
        req.on("continue", () => req.end("late body"));
      });
      expect(status).toBe(200);
    });
    expect(hits).toBe(1);
    expect(cassette.interactions).toHaveLength(0);
  });
});

describe("verify mode", () => {
  let server: Server;
  let origin: string;
  let hits: number;
  let reply: { status: number; headers: Record<string, string>; body: string };

  beforeEach(async () => {
    hits = 0;
    reply = { status: 200, headers: { "content-type": "application/json" }, body: '{"a":1}' };
    server = createServer((_req, res) => {
      hits += 1;
      res.writeHead(reply.status, { ...reply.headers, date: new Date(hits * 1e12).toUTCString() });
      res.end(reply.body);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterEach(() => {
    server.close();
  });

  async function record(path: string): Promise<string> {
    await useCassette(path, { recordMode: "all" }, async () => {
      await (await fetch(`${origin}/chat`)).text();
    });
    return readFileSync(path, "utf-8");
  }

  function verify(path: string, options: UseCassetteOptions = {}): Promise<Cassette> {
    return useCassette(path, { ...options, recordMode: "verify" }, async () => {
      await (await fetch(`${origin}/chat`)).text();
    });
  }

  it("sends a matched request live and never writes the cassette", async () => {
    const path = join(dir, "verify.yaml");
    const recorded = await record(path);

    await verify(path);

    expect(hits).toBe(2);
    expect(readFileSync(path, "utf-8")).toBe(recorded);
  });

  it("throws a unified diff when the live response differs", async () => {
    const path = join(dir, "verify.yaml");
    await record(path);
    reply = { ...reply, status: 201, body: '{"a":2}' };

    const error = await verify(path).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ResponseMismatchError);
    expect((error as Error).message).toBe(
      [
        `cassette ${path}, GET ${origin}/chat`,
        "--- recorded",
        "+++ live",
        "@@ -1,6 +1,6 @@",
        "-status: 200",
        "+status: 201",
        " @@ headers @@",
        " @@ json body @@",
        " {",
        '-  "a": 1',
        '+  "a": 2',
        " }",
      ].join("\n"),
    );
  });

  it("compares only the listed headers, with globs", async () => {
    const path = join(dir, "verify.yaml");
    reply.headers["x-price-estimate"] = "1";
    await record(path);
    reply.headers["x-other"] = "new";
    await verify(path, { compare: { headers: ["X-Price-*"] } });

    reply.headers["x-price-estimate"] = "2";
    await expect(verify(path, { compare: { headers: ["x-price-*"] } })).rejects.toThrow(
      /-x-price-estimate: 1\n\+x-price-estimate: 2/,
    );
  });

  it("ignores JSON paths and tolerates floats", async () => {
    const path = join(dir, "verify.yaml");
    reply.body = JSON.stringify({ id: "a", items: [{ id: 1, score: 0.1 }], total: 3 });
    await record(path);
    reply.body = JSON.stringify({ id: "b", items: [{ id: 2, score: 0.1000001 }], total: 3 });
    const compare = { jsonIgnore: ["id", "items[0].id"], floatTolerance: 1e-3 };

    await verify(path, { compare });

    reply.body = JSON.stringify({ id: "b", items: [{ id: 2, score: 0.2 }], total: 4 });
    const error = (await verify(path, { compare }).catch((e: unknown) => e)) as Error;
    expect(error.message).toContain('-      "score": 0.1\n+      "score": 0.2');
    expect(error.message).toContain('-  "total": 3\n+  "total": 4');
  });

  it("compares Server-Sent Events by their data payloads", async () => {
    const path = join(dir, "verify.yaml");
    reply = {
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: 'data: {"id":1,"delta":"hi"}\n\n: ping\n\ndata: [DONE]\n\n',
    };
    await record(path);
    reply.body = 'data: {"id":2,\r\ndata: "delta":"hi"}\r\n\r\ndata:[DONE]\r\n\r\n';
    const compare = { sse: true, jsonIgnore: ["id"] };

    await verify(path, { compare });

    reply.body = 'data: {"id":2,"delta":"bye"}\n\ndata: [DONE]\n\n';
    await expect(verify(path, { compare })).rejects.toThrow(
      /-    "delta": "hi"\n\+    "delta": "bye"/,
    );
  });

  it("compares other bodies as text", async () => {
    const path = join(dir, "verify.yaml");
    reply = { status: 200, headers: { "content-type": "text/plain" }, body: "one\ntwo" };
    await record(path);
    reply.body = "one\nthree";

    await expect(verify(path)).rejects.toThrow(/ one\n-two\n\+three/);
  });

  it("normalizes both responses with beforeCompareResponse", async () => {
    const path = join(dir, "verify.yaml");
    await record(path);
    reply.body = '{"a":1,"b":null}';
    const dropNulls = (response: HttpResponse): HttpResponse => ({
      ...response,
      body: {
        type: "json",
        content: Object.fromEntries(
          Object.entries(response.body.content as object).filter(([, value]) => value !== null),
        ),
      },
    });

    await expect(verify(path)).rejects.toThrow(ResponseMismatchError);
    await verify(path, {
      beforeCompareResponse: (recorded, live) => [dropNulls(recorded), dropNulls(live)],
    });
  });

  it("never tolerates a status change", async () => {
    const path = join(dir, "verify.yaml");
    await record(path);
    reply.status = 201;

    await expect(verify(path, { compare: { floatTolerance: 10 } })).rejects.toThrow(
      /-status: 200\n\+status: 201/,
    );
  });

  it("compares trailing newlines", async () => {
    const path = join(dir, "verify.yaml");
    reply = { status: 200, headers: { "content-type": "text/plain" }, body: "answer\n" };
    await record(path);
    reply.body = "answer";

    await expect(verify(path)).rejects.toThrow(/ answer\n-$/);
  });

  it("compares body types and top-level JSON scalars", async () => {
    const path = join(dir, "verify.yaml");
    reply.body = "1";
    await record(path);

    reply.body = '"1"';
    await expect(verify(path)).rejects.toThrow(/-1\n\+"1"/);
    reply = { status: 200, headers: { "content-type": "text/plain" }, body: "1" };
    await expect(verify(path)).rejects.toThrow(/-@@ json body @@\n\+@@ text body @@/);
  });

  it("ignores array elements", async () => {
    const path = join(dir, "verify.yaml");
    reply.body = '{"items":[1,2]}';
    await record(path);
    reply.body = '{"items":[3,2]}';

    await verify(path, { compare: { jsonIgnore: ["items[0]"] } });
  });

  it("compares header names case-insensitively", async () => {
    const path = join(dir, "verify.yaml");
    reply.headers["x-price-estimate"] = "1";
    await record(path);
    const yaml = readFileSync(path, "utf-8");
    writeFileSync(path, yaml.replace("x-price-estimate", "X-Price-Estimate"));

    await verify(path, { compare: { headers: ["x-price-*"] } });
  });

  it("does not leak scrubbed query parameters in the mismatch", async () => {
    const path = join(dir, "verify.yaml");
    const options = { filterQueryParameters: ["api_key"] };
    const call = async () => void (await fetch(`${origin}/chat?api_key=secret`)).text();
    await useCassette(path, { ...options, recordMode: "all" }, call);
    reply.status = 500;

    const error = (await useCassette(path, { ...options, recordMode: "verify" }, call).catch(
      (e: unknown) => e,
    )) as Error;
    expect(error).toBeInstanceOf(ResponseMismatchError);
    expect(error.message).not.toContain("secret");
  });

  it("bounds the diff of a large mismatch", async () => {
    const path = join(dir, "verify.yaml");
    const numbers = (offset: number) => Array.from({ length: 5000 }, (_, i) => i * 2 + offset);
    reply.body = JSON.stringify(numbers(0));
    await record(path);
    reply.body = JSON.stringify(numbers(1));

    const error = (await verify(path).catch((e: unknown) => e)) as Error;
    expect(error).toBeInstanceOf(ResponseMismatchError);
    expect(error.message).toContain("-  0,\n");
    expect(error.message).toContain("+  9999\n");
  });

  it("throws NoMatchError for an unmatched request", async () => {
    const path = join(dir, "verify.yaml");
    await record(path);

    await expect(
      useCassette(path, { recordMode: "verify" }, async () => {
        await fetch(`${origin}/other`);
      }),
    ).rejects.toThrow(NoMatchError);
    expect(hits).toBe(1);
  });

  it("fails the node:http response stream on a mismatch", async () => {
    const path = join(dir, "verify.yaml");
    await record(path);
    reply.body = '{"a":2}';

    await expect(
      useCassette(path, { recordMode: "verify" }, async () => {
        await new Promise((resolve, reject) => {
          httpGet(`${origin}/chat`, async (res) => {
            try {
              for await (const chunk of res) void chunk;
              resolve(undefined);
            } catch (e) {
              reject(e);
            }
          }).on("error", reject);
        });
      }),
    ).rejects.toThrow(ResponseMismatchError);
    expect(hits).toBe(2);
  });
});

describe("Google Cloud clients", () => {
  const cassettePath = join(dirname(fileURLToPath(import.meta.url)), "cassettes", "bigquery.yaml");

  it("replays a BigQuery query and its token exchange", async () => {
    // Delete the cassette to re-record with your Application Default Credentials.
    const credentials = existsSync(cassettePath)
      ? { type: "authorized_user", client_id: "replay", client_secret: "replay", refresh_token: "replay" }
      : undefined;

    const cassette = await useCassette(cassettePath, { bodyScrubPatterns: ["id_token"] }, async () => {
      const [rows] = await new BigQuery({ projectId: "pydantic-ai", credentials }).query(
        "SELECT word, word_count FROM `bigquery-public-data.samples.shakespeare` " +
          "WHERE corpus = 'hamlet' ORDER BY word_count DESC LIMIT 3",
      );
      expect(rows).toEqual([
        { word: "the", word_count: 995 },
        { word: "and", word_count: 706 },
        { word: "to", word_count: 635 },
      ]);
    });

    expect(cassette.interactions.map((i) => new URL(i.request.uri).hostname).sort()).toEqual([
      "bigquery.googleapis.com",
      "oauth2.googleapis.com",
    ]);
  });
});
