import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  native,
  processBody,
  scrubGrpcInteraction,
  scrubInteraction,
  scrubWsInteraction,
} from "../src/binding.js";
import { bodyToBuffer, NONE_BODY } from "../src/types.js";
import type { Body, HeaderMap, HttpRequest, Matcher, SecurityConfig } from "../src/types.js";
import {
  canonicalBody,
  canonicalCassette,
  CONFORMANCE_ROOT,
} from "./conformance-helpers.js";

const FIXTURES = join(CONFORMANCE_ROOT, "conformance");

type MatchingRequest = {
  method: string;
  uri: string;
  headers?: HeaderMap;
  body?: Body;
};

type MatchingCase = {
  name: string;
  matchOn?: Matcher[];
  ignoreJsonPaths?: string[];
  requests: MatchingRequest[];
  expectedStatuses: Array<number | null>;
};

type FilteringCase = {
  name: string;
  filterHeaders?: string[];
  filterQueryParameters?: string[];
  bodyScrubPatterns?: string[];
  replacement?: string;
  expected: string;
};

function readJson<T>(...path: string[]): T {
  return JSON.parse(readFileSync(join(...path), "utf-8")) as T;
}

function header(headers: HeaderMap, name: string): string | undefined {
  const entry = Object.entries(headers).find(([key]) => key.toLowerCase() === name);
  return entry?.[1][0];
}

function matchingRequest(value: MatchingRequest): HttpRequest {
  return {
    method: value.method,
    uri: value.uri,
    headers: value.headers ?? {},
    body: value.body ?? NONE_BODY,
  };
}

describe("cross-language body processing conformance", () => {
  it("processes the shared YAML cases", () => {
    const directory = join(FIXTURES, "body-processing");
    const cassette = native.Cassette.load(join(directory, "cases.yaml"));
    const expected = readJson<Record<string, object>>(directory, "expected.json");
    const actual = Object.fromEntries(
      cassette.interactions.map((interaction) => [
        interaction.request.uri,
        canonicalBody(
          processBody(
            bodyToBuffer(interaction.response.body),
            header(interaction.response.headers, "content-type"),
            header(interaction.response.headers, "content-encoding"),
          ),
        ),
      ]),
    );

    expect(actual).toEqual(expected);
  });
});

describe("cross-language matching conformance", () => {
  const directory = join(FIXTURES, "matching");
  const cases = readJson<MatchingCase[]>(directory, "cases.json");

  it.each(cases)("matches $name", (case_) => {
    const cassette = native.Cassette.load(join(directory, "cassette.yaml"));
    const statuses = case_.requests.map((request) => {
      const hit = cassette.takeMatch(matchingRequest(request), {
        matchOn: case_.matchOn,
        ignoreJsonPaths: case_.ignoreJsonPaths,
      });
      return hit?.interaction.response.status ?? null;
    });

    expect(statuses).toEqual(case_.expectedStatuses);
  });
});

describe("cross-language filtering conformance", () => {
  const directory = join(FIXTURES, "filtering");
  const cases = readJson<FilteringCase[]>(directory, "cases.json");

  it.each(cases)("scrubs $name", (case_) => {
    const cassette = native.Cassette.load(join(directory, "input.yaml"));
    const config: SecurityConfig = {
      filterHeaders: case_.filterHeaders,
      filterQueryParameters: case_.filterQueryParameters,
      bodyScrubPatterns: case_.bodyScrubPatterns,
      replacement: case_.replacement,
    };
    const actual = canonicalCassette({
      version: cassette.version,
      interactions: cassette.interactions.map((value) => scrubInteraction(value, config)),
      grpcInteractions: cassette.grpcInteractions.map((value) =>
        scrubGrpcInteraction(value, config),
      ),
      wsInteractions: cassette.wsInteractions.map((value) =>
        scrubWsInteraction(value, config),
      ),
    });
    const expected = readJson<object>(directory, case_.expected);

    expect(actual).toEqual(expected);
  });
});
