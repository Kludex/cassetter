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
    const c = new Cassette(join(dir, "m.yaml"), {
      recordMode: RecordMode.ALL,
      matchConfig: {
        matchOn: ["method", "uri", "json_body"],
        ignoreJsonPaths: ["timestamp"],
      },
    });
    c.load();
    c.record(
      "POST",
      "https://api.example.com/q",
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ q: "hi", timestamp: "A" })),
      200,
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ ok: true })),
    );

    // Same query, different ignored timestamp -> still a match.
    const res = c.play(
      "POST",
      "https://api.example.com/q",
      { "content-type": ["application/json"] },
      Buffer.from(JSON.stringify({ q: "hi", timestamp: "B" })),
    );
    expect(res.status).toBe(200);
  });

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

  it("preserves file permissions across a rewrite", () => {
    const p = write("perm.yaml");
    chmodSync(p, 0o600);

    const c = new Cassette(p, { recordMode: RecordMode.REWRITE });
    c.load();
    c.record("GET", "https://api.example.com/p", {}, null, 200, {}, Buffer.from("x"));
    c.save();

    // The temp file is created at the process umask, so without carrying the
    // mode over a 0600 cassette would come back world-readable.
    expect(statSync(p).mode & 0o777).toBe(0o600);
  });
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
