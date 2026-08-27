/**
 * Record modes and duration parsing.
 */

export enum RecordMode {
  /** Replay only. Throws if no match is found. */
  NONE = "none",
  /** Record if the cassette doesn't exist; replay if it does. */
  ONCE = "once",
  /** Replay existing interactions, record new ones. */
  NEW_EPISODES = "new_episodes",
  /** Record everything, overwriting the cassette. */
  ALL = "all",
  /** Delete the cassette, then record everything. */
  REWRITE = "rewrite",
}

const RECORD_MODES: Record<string, RecordMode> = {
  none: RecordMode.NONE,
  once: RecordMode.ONCE,
  new_episodes: RecordMode.NEW_EPISODES,
  all: RecordMode.ALL,
  rewrite: RecordMode.REWRITE,
};

/** Modes that discard whatever the cassette already held. */
export const DISCARDING_MODES: readonly RecordMode[] = [
  RecordMode.ALL,
  RecordMode.REWRITE,
];

/** Parse a record mode name, accepting hyphens for underscores. */
export function parseRecordMode(value: string): RecordMode {
  const mode = RECORD_MODES[value.toLowerCase().replace(/-/g, "_")];
  if (mode === undefined) {
    throw new Error(
      `unknown record mode: '${value}', expected one of ${Object.keys(RECORD_MODES).join(", ")}`,
    );
  }
  return mode;
}

const DURATION_RE = /^(\d+)([dhw])$/;
const UNIT_MS: Record<string, number> = {
  h: 60 * 60 * 1000,
  d: 24 * 60 * 60 * 1000,
  w: 7 * 24 * 60 * 60 * 1000,
};

/** Parse a duration like `30d`, `24h`, or `4w` into milliseconds. */
export function parseDuration(s: string): number {
  const m = DURATION_RE.exec(s);
  if (!m) {
    throw new Error(`invalid duration string: '${s}' (expected <number><d|h|w>)`);
  }
  return parseInt(m[1], 10) * UNIT_MS[m[2]];
}
