/** Cross-language cassette-format conformance. */

import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { native } from "../src/binding.js";
import { canonicalCassette, CONFORMANCE_ROOT } from "./conformance-helpers.js";

const FORMAT_FIXTURES = join(CONFORMANCE_ROOT, "conformance", "format");

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

function expected(case_: FormatCase): object {
  return JSON.parse(
    readFileSync(join(FORMAT_FIXTURES, case_.expected), "utf-8"),
  ) as object;
}

describe("cross-language format conformance", () => {
  it.each(CASES)("parses $name into the canonical structure", (case_) => {
    const cassette = native.Cassette.load(join(FORMAT_FIXTURES, case_.cassette));
    expect(canonicalCassette(cassette)).toEqual(expected(case_));
  });

  it.each(CASES)("round-trips $name through its storage format without drift", (case_) => {
    const directory = mkdtempSync(join(tmpdir(), "cassetter-conf-"));
    try {
      const output = join(directory, case_.cassette);
      native.Cassette.load(join(FORMAT_FIXTURES, case_.cassette)).save(output);
      expect(canonicalCassette(native.Cassette.load(output))).toEqual(expected(case_));
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
