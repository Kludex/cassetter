import { describe, it, expect } from "vitest";
import { RecordMode, parseRecordMode, parseDuration } from "../src/recording.js";

describe("RecordMode", () => {
  it("has the expected values", () => {
    expect(RecordMode.NONE).toBe("none");
    expect(RecordMode.ONCE).toBe("once");
    expect(RecordMode.NEW_EPISODES).toBe("new_episodes");
    expect(RecordMode.ALL).toBe("all");
  });
});

describe("parseRecordMode", () => {
  it("parses valid modes", () => {
    expect(parseRecordMode("none")).toBe(RecordMode.NONE);
    expect(parseRecordMode("once")).toBe(RecordMode.ONCE);
    expect(parseRecordMode("new_episodes")).toBe(RecordMode.NEW_EPISODES);
    expect(parseRecordMode("all")).toBe(RecordMode.ALL);
  });

  it("is case insensitive", () => {
    expect(parseRecordMode("NONE")).toBe(RecordMode.NONE);
    expect(parseRecordMode("Once")).toBe(RecordMode.ONCE);
  });

  it("normalizes hyphens to underscores", () => {
    expect(parseRecordMode("new-episodes")).toBe(RecordMode.NEW_EPISODES);
  });

  it("throws on unknown mode", () => {
    expect(() => parseRecordMode("invalid")).toThrow("unknown record mode");
  });
});

describe("parseDuration", () => {
  it("parses days", () => {
    expect(parseDuration("30d")).toBe(30 * 24 * 60 * 60 * 1000);
  });

  it("parses hours", () => {
    expect(parseDuration("24h")).toBe(24 * 60 * 60 * 1000);
  });

  it("parses weeks", () => {
    expect(parseDuration("4w")).toBe(4 * 7 * 24 * 60 * 60 * 1000);
  });

  it("throws on invalid format", () => {
    expect(() => parseDuration("invalid")).toThrow("invalid duration string");
    expect(() => parseDuration("30m")).toThrow("invalid duration string");
    expect(() => parseDuration("")).toThrow("invalid duration string");
  });
});
