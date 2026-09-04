/**
 * Cross-language conformance.
 *
 * Parses the shared fixture in `conformance/` and asserts it produces the
 * canonical structure every cassetter binding must agree on. The Python
 * binding runs the same assertions in `tests/test_conformance.py`.
 */

import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { native } from "../src/binding.js";
import type {
  Body,
  GrpcInteraction,
  HeaderMap,
  HttpInteraction,
  WsInteraction,
} from "../src/types.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const FIXTURE = join(ROOT, "conformance", "cassette.yaml");
const EXPECTED = join(ROOT, "conformance", "expected.json");

function sortKeys<T extends object>(o: T): T {
  return Object.fromEntries(
    Object.entries(o).sort(([a], [b]) => (a < b ? -1 : 1)),
  ) as T;
}

function body(b: Body): object {
  return b.type === "none" ? { type: "none" } : { type: b.type, content: b.content };
}

function headers(h: HeaderMap): HeaderMap {
  return sortKeys(h);
}

function canonical(c: {
  version: number;
  interactions: HttpInteraction[];
  grpcInteractions: GrpcInteraction[];
  wsInteractions: WsInteraction[];
}): object {
  return {
    version: c.version,
    http: c.interactions.map((i) => ({
      method: i.request.method,
      uri: i.request.uri,
      requestHeaders: headers(i.request.headers),
      requestBody: body(i.request.body),
      status: i.response.status,
      responseHeaders: headers(i.response.headers),
      responseBody: body(i.response.body),
      recordedAt: i.recordedAt,
    })),
    grpc: c.grpcInteractions.map((g) => ({
      method: g.request.method,
      metadata: headers(g.request.metadata),
      requestBody: body(g.request.body),
      statusCode: g.response.statusCode,
      statusMessage: g.response.statusMessage,
      responseMetadata: headers(g.response.metadata),
      responseBody: body(g.response.body),
      jsonDebug: g.jsonDebug ?? null,
      recordedAt: g.recordedAt,
    })),
    ws: c.wsInteractions.map((w) => ({
      uri: w.uri,
      headers: headers(w.headers),
      frames: w.frames.map((f) => ({
        direction: f.direction,
        frameType: f.frameType,
        body: body(f.body),
        offsetMs: f.offsetMs,
      })),
      recordedAt: w.recordedAt,
    })),
  };
}

describe("cross-language conformance", () => {
  const expected = JSON.parse(readFileSync(EXPECTED, "utf-8"));

  it("parses the shared fixture into the canonical structure", () => {
    expect(canonical(native.Cassette.load(FIXTURE))).toEqual(expected);
  });

  it("round-trips the fixture through YAML without drift", () => {
    const dir = mkdtempSync(join(tmpdir(), "cassetter-conf-"));
    try {
      const out = join(dir, "roundtrip.yaml");
      native.Cassette.load(FIXTURE).save(out);
      expect(canonical(native.Cassette.load(out))).toEqual(expected);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("preserves unicode and multi-value headers", () => {
    const c = native.Cassette.load(FIXTURE);
    expect(c.interactions[1].request.body.content).toBe("café — naïve ✓");
    expect(c.interactions[0].request.headers["x-multi"]).toEqual(["one", "two"]);
  });
});
