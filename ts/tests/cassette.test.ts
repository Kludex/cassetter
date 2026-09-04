import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  Cassette,
  CassetteExpiredError,
  CassetteLoadError,
  NoMatchError,
  getHeader,
} from "../src/cassette.js";
import { RecordMode } from "../src/recording.js";
import type { MatchConfig } from "../src/types.js";

const SAMPLE = `version: 1
interactions:
- request:
    method: GET
    uri: https://api.example.com/users
    headers:
      accept:
      - application/json
    body:
      type: none
  response:
    status: 200
    headers:
      content-type:
      - application/json
    body:
      type: json
      content:
        users:
        - id: 1
          name: Alice
  recorded_at: '2026-01-01T00:00:00Z'
`;

let dir: string;

beforeEach(() => {
  dir = join(tmpdir(), `cassetter-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  mkdirSync(dir, { recursive: true });
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function write(name: string, content = SAMPLE): string {
  const p = join(dir, name);
  writeFileSync(p, content);
  return p;
}

describe("load", () => {
  it("reads an existing cassette", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();

    expect(c.interactions).toHaveLength(1);
    expect(c.interactions[0].request.method).toBe("GET");
    expect(c.interactions[0].recordedAt).toBe("2026-01-01T00:00:00Z");
  });

  it("starts empty when the file is missing", () => {
    const c = new Cassette(join(dir, "missing.yaml"), {
      recordMode: RecordMode.ONCE,
    });
    c.load();
    expect(c.interactions).toHaveLength(0);
  });

  it("ignores existing content in ALL mode", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.ALL });
    c.load();
    expect(c.interactions).toHaveLength(0);
  });

  it("reports a parse failure as CassetteLoadError", () => {
    const c = new Cassette(write("bad.yaml", "{{{ not yaml"), {
      recordMode: RecordMode.NONE,
    });
    expect(() => c.load()).toThrow(CassetteLoadError);
  });
});

describe("record modes", () => {
  it("once replays without recording when the cassette exists", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.ONCE });
    c.load();
    // An existing cassette must not silently hit the network and append.
    expect(c.canRecord).toBe(false);
  });

  it("once records when the cassette did not exist", () => {
    const c = new Cassette(join(dir, "new.yaml"), { recordMode: RecordMode.ONCE });
    c.load();
    expect(c.canRecord).toBe(true);
  });

  it("none never records", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();
    expect(c.canRecord).toBe(false);
  });

  it.each([RecordMode.ALL, RecordMode.NEW_EPISODES, RecordMode.REWRITE])(
    "%s records",
    (mode) => {
      const c = new Cassette(write("t.yaml"), { recordMode: mode });
      c.load();
      expect(c.canRecord).toBe(true);
    },
  );

  it("rewrite deletes the cassette up front", () => {
    const path = write("t.yaml");
    const c = new Cassette(path, { recordMode: RecordMode.REWRITE });
    c.load();
    // Dropped before recording, so a run that captures nothing leaves no
    // stale cassette behind.
    expect(existsSync(path)).toBe(false);
    expect(c.interactions).toHaveLength(0);
  });
});

describe("play", () => {
  it("replays a matching interaction", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();

    const res = c.play("GET", "https://api.example.com/users", {}, null);
    expect(res.status).toBe(200);
    expect(res.body.type).toBe("json");
    expect(res.body.content).toEqual({ users: [{ id: 1, name: "Alice" }] });
  });

  it("matches case-insensitively on method", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();
    expect(c.play("get", "https://api.example.com/users", {}, null).status).toBe(200);
  });

  it("throws NoMatchError when nothing matches", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();
    expect(() => c.play("POST", "https://api.example.com/other", {}, null)).toThrow(
      NoMatchError,
    );
  });

  it("throws when the cassette was never loaded", () => {
    const c = new Cassette(join(dir, "x.yaml"));
    expect(() => c.play("GET", "https://x.test", {}, null)).toThrow(NoMatchError);
  });

  it("rejects an unknown matcher instead of matching everything", () => {
    const c = new Cassette(write("t.yaml"), {
      recordMode: RecordMode.NONE,
      matchConfig: { matchOn: ["bogus" as never] },
    });
    c.load();
    expect(() => c.play("GET", "https://api.example.com/users", {}, null)).toThrow();
  });

  it("respects a custom matchOn with ignored JSON paths", () => {
    const path = join(dir, "m.yaml");
    const matchConfig: MatchConfig = {
      matchOn: ["method", "uri", "json_body"],
      ignoreJsonPaths: ["timestamp"],
    };
    const recorded = new Cassette(path, {
      recordMode: RecordMode.ALL,
      matchConfig,
    });
    recorded.load();
    recorded.record(
      "POST",
      "https://api.example.com/q",
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ q: "hi", timestamp: "A" })),
      200,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ ok: true })),
    );
    recorded.save();

    const replayed = new Cassette(path, {
      recordMode: RecordMode.NONE,
      matchConfig,
    });
    replayed.load();

    // Same query, different ignored timestamp -> still a match.
    const res = replayed.play(
      "POST",
      "https://api.example.com/q",
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ q: "hi", timestamp: "B" })),
    );
    expect(res.status).toBe(200);
  });

  it.each([RecordMode.ALL, RecordMode.REWRITE])(
    "%s mode does not replay a newly recorded interaction",
    (recordMode) => {
      const c = new Cassette(join(dir, "discard.yaml"), { recordMode });
      c.load();
      c.record("GET", "https://api.example.com/users", {}, null, 200, {}, null);

      expect(() =>
        c.play("GET", "https://api.example.com/users", {}, null),
      ).toThrow(NoMatchError);
      expect(c.interactions).toHaveLength(1);
    },
  );

  it("marks an interaction played so it is not reused first", () => {
    const c = new Cassette(write("t.yaml"), { recordMode: RecordMode.NONE });
    c.load();
    c.play("GET", "https://api.example.com/users", {}, null);
    // Falls back to the played interaction rather than failing.
    expect(c.play("GET", "https://api.example.com/users", {}, null).status).toBe(200);
  });
});

describe("record", () => {
  it("records and scrubs by default", () => {
    const c = new Cassette(join(dir, "r.yaml"), { recordMode: RecordMode.ALL });
    c.load();

    const res = c.record(
      "POST",
      "https://api.example.com/login?api_key=s3cret",
      { authorization: ["Bearer t"], "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ password: "hunter2", user: "kate" })),
      201,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ ok: true })),
    );

    expect(res.status).toBe(201);
    expect(c.interactions).toHaveLength(1);

    const rec = c.interactions[0];
    expect(rec.request.headers.authorization).toBeUndefined();
    expect(rec.request.uri).not.toContain("s3cret");
    const body = rec.request.body.content as Record<string, unknown>;
    expect(body.password).toBe("[FILTERED]");
    expect(body.user).toBe("kate");
  });

  it("strips content-encoding after decompressing", () => {
    const c = new Cassette(join(dir, "g.yaml"), { recordMode: RecordMode.ALL });
    c.load();

    c.record(
      "GET",
      "https://api.example.com/z",
      {},
      null,
      200,
      { "content-type": ["application/json"], "content-encoding": ["gzip"] },
      gzipSync(Buffer.from(JSON.stringify({ z: 1 }))),
    );

    const rec = c.interactions[0];
    expect(rec.response.headers["content-encoding"]).toBeUndefined();
    expect(rec.response.body.content).toEqual({ z: 1 });
  });
});

describe("save", () => {
  it("writes a recorded cassette", () => {
    const p = join(dir, "nested", "out.yaml");
    const c = new Cassette(p, { recordMode: RecordMode.ALL });
    c.load();
    c.record("GET", "https://api.example.com/t", {}, null, 200, {}, Buffer.from("ok"));
    c.save();

    expect(existsSync(p)).toBe(true);
    const yaml = readFileSync(p, "utf-8");
    expect(yaml).toContain("version: 1");
    expect(yaml).toContain("uri: https://api.example.com/t");
  });

  it("does not write an empty cassette when no file existed", () => {
    const p = join(dir, "empty.yaml");
    const c = new Cassette(p, { recordMode: RecordMode.ONCE });
    c.load();
    c.save();
    expect(existsSync(p)).toBe(false);
  });

  it("truncates a stale cassette when a re-record captured nothing", () => {
    const p = write("stale.yaml");
    const c = new Cassette(p, { recordMode: RecordMode.ALL });
    c.load();
    c.save();
    expect(existsSync(p)).toBe(true);
    expect(readFileSync(p, "utf-8")).not.toContain("api.example.com");
  });

  it("round-trips through YAML without loss", () => {
    const p = join(dir, "rt.yaml");
    const a = new Cassette(p, { recordMode: RecordMode.ALL });
    a.load();
    a.record(
      "POST",
      "https://api.example.com/rt",
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ nested: { list: [1, 2, 3] } })),
      200,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ deep: { ok: true } })),
    );
    a.save();

    const b = new Cassette(p, { recordMode: RecordMode.NONE });
    b.load();
    expect(b.interactions[0].request.body.content).toEqual({
      nested: { list: [1, 2, 3] },
    });
    expect(b.interactions[0].response.body.content).toEqual({ deep: { ok: true } });
  });

  it("round-trips through TOML", () => {
    const p = join(dir, "rt.toml");
    const a = new Cassette(p, { recordMode: RecordMode.ALL });
    a.load();
    a.record(
      "GET",
      "https://api.example.com/toml",
      {},
      null,
      200,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ ok: true })),
    );
    a.save();
    expect(readFileSync(p, "utf-8")).toContain("[[interactions]]");

    const b = new Cassette(p, { recordMode: RecordMode.NONE });
    b.load();
    expect(b.interactions[0].response.body.content).toEqual({ ok: true });
  });

  // POSIX only: Windows chmod toggles the read-only bit and nothing else, and
  // the Rust writer only restores a mode under #[cfg(unix)].
  it.skipIf(process.platform === "win32")(
    "preserves file permissions across a rewrite",
    () => {
      const p = write("perm.yaml");
      chmodSync(p, 0o600);

      const c = new Cassette(p, { recordMode: RecordMode.REWRITE });
      c.load();
      c.record("GET", "https://api.example.com/p", {}, null, 200, {}, Buffer.from("x"));
      c.save();

      // The temp file is created at the process umask, so without carrying
      // the mode over a 0600 cassette would come back world-readable.
      expect(statSync(p).mode & 0o777).toBe(0o600);
    },
  );
});

describe("expiry", () => {
  const stale = SAMPLE.replace("2026-01-01T00:00:00Z", "2020-01-01T00:00:00Z");

  it("throws when onExpiry is fail", () => {
    const c = new Cassette(write("old.yaml", stale), {
      recordMode: RecordMode.NONE,
      maxAge: "1d",
      onExpiry: "fail",
    });
    expect(() => c.load()).toThrow(CassetteExpiredError);
  });

  it("clears the cassette when onExpiry is rerecord", () => {
    const c = new Cassette(write("old.yaml", stale), {
      recordMode: RecordMode.ONCE,
      maxAge: "1d",
      onExpiry: "rerecord",
    });
    c.load();
    expect(c.interactions).toHaveLength(0);
    // A cleared cassette must be recordable again, or the run has nothing.
    expect(c.canRecord).toBe(true);
  });

  it("keeps a fresh cassette", () => {
    const fresh = SAMPLE.replace("2026-01-01T00:00:00Z", new Date().toISOString());
    const c = new Cassette(write("fresh.yaml", fresh), {
      recordMode: RecordMode.NONE,
      maxAge: "30d",
      onExpiry: "fail",
    });
    c.load();
    expect(c.interactions).toHaveLength(1);
  });
});

describe("getHeader", () => {
  it("looks up case-insensitively", () => {
    expect(getHeader({ "Content-Type": ["application/json"] }, "content-type")).toBe(
      "application/json",
    );
    expect(getHeader({}, "content-type")).toBeNull();
    expect(getHeader({ "x-a": [] }, "x-a")).toBeNull();
  });
});

describe("scrubbed values still replay", () => {
  // Recording writes a scrubbed interaction, so the live request has to be
  // scrubbed the same way before it is matched against one.
  it("matches a URI whose query param was filtered at write time", () => {
    const p = join(dir, "q.yaml");
    const a = new Cassette(p, { recordMode: RecordMode.ALL });
    a.load();
    a.record(
      "GET",
      "https://api.example.com/data?api_key=s3cret&page=2",
      {},
      null,
      200,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ ok: true })),
    );
    a.save();
    // What landed on disk is the filtered URI, not the live one.
    expect(a.interactions[0].request.uri).toContain("[FILTERED]");

    const b = new Cassette(p, { recordMode: RecordMode.NONE });
    b.load();
    const res = b.play(
      "GET",
      "https://api.example.com/data?api_key=s3cret&page=2",
      {},
      null,
    );
    expect(res.status).toBe(200);
  });

  it("matches a body whose fields were scrubbed at write time", () => {
    const p = join(dir, "b.yaml");
    const headers = { "content-type": ["application/json"] };
    const live = Buffer.from(JSON.stringify({ user: "kate", password: "hunter2" }));

    const a = new Cassette(p, {
      recordMode: RecordMode.ALL,
      matchConfig: { matchOn: ["method", "uri", "json_body"] },
    });
    a.load();
    a.record(
      "POST",
      "https://api.example.com/login",
      headers,
      live,
      200,
      headers,
      Buffer.from(JSON.stringify({ ok: true })),
    );
    a.save();

    const b = new Cassette(p, {
      recordMode: RecordMode.NONE,
      matchConfig: { matchOn: ["method", "uri", "json_body"] },
    });
    b.load();
    expect(b.play("POST", "https://api.example.com/login", headers, live).status).toBe(
      200,
    );
  });
});

describe("WebSocket security", () => {
  it("replays a URI whose query parameter was filtered", () => {
    const path = join(dir, "ws.yaml");
    const uri = "wss://api.example.com/socket?access_token=secret";
    const recorded = new Cassette(path, { recordMode: RecordMode.ALL });
    recorded.load();
    recorded.recordWs(uri, {}, []);
    recorded.save();

    const replayed = new Cassette(path, { recordMode: RecordMode.NONE });
    replayed.load();

    expect(replayed.playWs(uri).uri).toContain("access_token=[FILTERED]");
  });
});

describe("record order", () => {
  it("writes interactions in the order requests were issued", () => {
    const p = join(dir, "order.yaml");
    const c = new Cassette(p, { recordMode: RecordMode.ALL });
    c.load();

    // Two indistinguishable requests whose responses land out of order.
    const first = c.reserveRecordOrder();
    const second = c.reserveRecordOrder();

    const headers = { "content-type": ["application/json"] };
    c.record("GET", "https://api.example.com/n", {}, null, 200, headers,
      Buffer.from(JSON.stringify({ n: 2 })), second);
    c.record("GET", "https://api.example.com/n", {}, null, 200, headers,
      Buffer.from(JSON.stringify({ n: 1 })), first);
    c.save();

    const replayed = new Cassette(p, { recordMode: RecordMode.NONE });
    replayed.load();
    // The one issued first is served first, not the one that finished first.
    expect(replayed.play("GET", "https://api.example.com/n", {}, null).body.content)
      .toEqual({ n: 1 });
    expect(replayed.play("GET", "https://api.example.com/n", {}, null).body.content)
      .toEqual({ n: 2 });
  });

  it("hands out increasing positions", () => {
    const c = new Cassette(join(dir, "o.yaml"), { recordMode: RecordMode.ALL });
    c.load();
    expect([c.reserveRecordOrder(), c.reserveRecordOrder()]).toEqual([0, 1]);
  });
});

describe("content-length", () => {
  it("restates the header for the body actually recorded", () => {
    const c = new Cassette(join(dir, "cl.yaml"), { recordMode: RecordMode.ALL });
    c.load();

    const plain = JSON.stringify({ ok: true });
    c.record(
      "GET",
      "https://api.example.com/z",
      {},
      null,
      200,
      {
        "content-type": ["application/json"],
        "content-encoding": ["gzip"],
        // The compressed length, which no longer describes what we store.
        "content-length": ["999"],
      },
      gzipSync(Buffer.from(plain)),
    );

    const rec = c.interactions[0];
    expect(rec.response.headers["content-encoding"]).toBeUndefined();
    expect(rec.response.headers["content-length"]).toEqual([
      String(Buffer.byteLength(plain)),
    ]);
  });

  it("leaves a body-less response alone", () => {
    const c = new Cassette(join(dir, "cl2.yaml"), { recordMode: RecordMode.ALL });
    c.load();
    c.record("HEAD", "https://api.example.com/h", {}, null, 204,
      { "content-length": ["42"] }, null);
    expect(c.interactions[0].response.headers["content-length"]).toEqual(["42"]);
  });
});

describe("re-loading the same cassette object", () => {
  it("records again once the file it replayed from is gone", () => {
    const p = write("reload.yaml");
    const c = new Cassette(p, { recordMode: RecordMode.ONCE });

    c.load();
    // The file was there, so `once` replays only.
    expect(c.canRecord).toBe(false);

    rmSync(p, { force: true });
    c.load();
    // With nothing to replay from, it must be free to record again.
    expect(c.canRecord).toBe(true);
    expect(c.interactions).toHaveLength(0);
  });
});
