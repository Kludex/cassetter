/** Cross-language cassette-format conformance. */

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
const FORMAT_FIXTURES = join(ROOT, "conformance", "format");

type FormatCase = {
  name: string;
  cassette: string;
  expected: string;
};

type InvalidFormatCase = {
  name: string;
  cassette: string;
};

const CASES = JSON.parse(
  readFileSync(join(FORMAT_FIXTURES, "cases.json"), "utf-8"),
) as FormatCase[];
const INVALID_CASES = JSON.parse(
  readFileSync(join(FORMAT_FIXTURES, "invalid", "cases.json"), "utf-8"),
) as InvalidFormatCase[];

function sortKeys<T extends object>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).sort(([left], [right]) => (left < right ? -1 : 1)),
  ) as T;
}

function body(value: Body): object {
  return value.type === "none"
    ? { type: "none" }
    : { type: value.type, content: value.content };
}

function headers(value: HeaderMap): HeaderMap {
  return sortKeys(value);
}

function canonical(cassette: {
  version: number;
  interactions: HttpInteraction[];
  grpcInteractions: GrpcInteraction[];
  wsInteractions: WsInteraction[];
}): object {
  return {
    version: cassette.version,
    http: cassette.interactions.map((interaction) => ({
      method: interaction.request.method,
      uri: interaction.request.uri,
      requestHeaders: headers(interaction.request.headers),
      requestBody: body(interaction.request.body),
      status: interaction.response.status,
      responseHeaders: headers(interaction.response.headers),
      responseBody: body(interaction.response.body),
      recordedAt: interaction.recordedAt,
    })),
    grpc: cassette.grpcInteractions.map((interaction) => ({
      method: interaction.request.method,
      metadata: headers(interaction.request.metadata),
      requestBody: body(interaction.request.body),
      statusCode: interaction.response.statusCode,
      statusMessage: interaction.response.statusMessage,
      responseMetadata: headers(interaction.response.metadata),
      responseBody: body(interaction.response.body),
      jsonDebug: interaction.jsonDebug ?? null,
      recordedAt: interaction.recordedAt,
    })),
    ws: cassette.wsInteractions.map((interaction) => ({
      uri: interaction.uri,
      headers: headers(interaction.headers),
      frames: interaction.frames.map((frame) => ({
        direction: frame.direction,
        frameType: frame.frameType,
        body: body(frame.body),
        offsetMs: frame.offsetMs,
      })),
      recordedAt: interaction.recordedAt,
    })),
  };
}

function expected(case_: FormatCase): object {
  return JSON.parse(
    readFileSync(join(FORMAT_FIXTURES, case_.expected), "utf-8"),
  ) as object;
}

describe("cross-language format conformance", () => {
  it.each(CASES)("parses $name into the canonical structure", (case_) => {
    const cassette = native.Cassette.load(join(FORMAT_FIXTURES, case_.cassette));
    expect(canonical(cassette)).toEqual(expected(case_));
  });

  it.each(CASES)("round-trips $name through YAML without drift", (case_) => {
    const directory = mkdtempSync(join(tmpdir(), "cassetter-conf-"));
    try {
      const output = join(directory, case_.cassette);
      native.Cassette.load(join(FORMAT_FIXTURES, case_.cassette)).save(output);
      expect(canonical(native.Cassette.load(output))).toEqual(expected(case_));
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it.each(INVALID_CASES)("rejects $name", (case_) => {
    expect(() =>
      native.Cassette.load(join(FORMAT_FIXTURES, "invalid", case_.cassette)),
    ).toThrow();
  });

  it("preserves unicode and multi-value headers", () => {
    const cassette = native.Cassette.load(
      join(FORMAT_FIXTURES, "all-protocols.yaml"),
    );
    expect(cassette.interactions[1].request.body.content).toBe("café — naïve ✓");
    expect(cassette.interactions[0].request.headers["x-multi"]).toEqual(["one", "two"]);
  });
});
