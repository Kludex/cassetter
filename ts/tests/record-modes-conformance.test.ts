import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, it } from "vitest";

import { native } from "../src/binding.js";
import { Cassette, NoMatchError } from "../src/cassette.js";
import { RecordMode } from "../src/recording.js";
import { CONFORMANCE_ROOT } from "./conformance-helpers.js";

const FIXTURES = join(CONFORMANCE_ROOT, "conformance", "record-modes");

type StoredInteraction = {
  uri: string;
  status: number;
};

type RecordModeCase = {
  name: string;
  mode: RecordMode;
  existing: boolean;
  requests: string[];
  expectedOutcomes: string[];
  expectedBaseCalls: number;
  expectedFile: StoredInteraction[] | null;
};

const CASES = JSON.parse(
  readFileSync(join(FIXTURES, "cases.json"), "utf-8"),
) as RecordModeCase[];

it.each(CASES)("applies shared record mode case: $name", (case_) => {
  const directory = mkdtempSync(join(tmpdir(), "cassetter-modes-"));
  const path = join(directory, "cassette.yaml");
  try {
    if (case_.existing) {
      copyFileSync(join(FIXTURES, "existing.yaml"), path);
    }
    const cassette = new Cassette(path, { recordMode: case_.mode });
    cassette.load();
    const outcomes: string[] = [];
    let baseCalls = 0;

    for (const uri of case_.requests) {
      try {
        cassette.play("GET", uri, {}, null);
        outcomes.push("replay");
      } catch (error) {
        if (!(error instanceof NoMatchError)) {
          throw error;
        }
        if (!cassette.canRecord) {
          outcomes.push("no_match");
          continue;
        }
        cassette.record(
          "GET",
          uri,
          {},
          null,
          299,
          { "content-type": ["application/json"] },
          Buffer.from('{"source":"live"}'),
        );
        outcomes.push("live");
        baseCalls += 1;
      }
    }
    cassette.save();

    expect(outcomes).toEqual(case_.expectedOutcomes);
    expect(baseCalls).toBe(case_.expectedBaseCalls);
    if (case_.expectedFile === null) {
      expect(existsSync(path)).toBe(false);
    } else {
      const stored = native.Cassette.load(path);
      const actual = stored.interactions
        .map((interaction) => ({
          uri: interaction.request.uri,
          status: interaction.response.status,
        }))
        .sort((left, right) => left.uri.localeCompare(right.uri));
      expect(actual).toEqual(case_.expectedFile);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
