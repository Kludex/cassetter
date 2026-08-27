import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { NoMatchError } from "../src/cassette.js";
import { useCassette } from "../src/context.js";

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
