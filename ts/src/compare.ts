/**
 * Response comparison for the `verify` record mode.
 */

import type { HttpResponse } from "./types.js";

/** Raised in `verify` mode when a live response differs from its recording. */
export class ResponseMismatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResponseMismatchError";
  }
}

/**
 * What `verify` mode compares between a recorded response and the live one.
 *
 * The status is always compared. Everything not listed here is ignored.
 */
export interface Compare {
  /** Response header names to compare by value. Globs such as `x-price-*` are allowed. */
  headers?: string[];
  /**
   * Paths removed from JSON bodies before comparing, in the `ignoreJsonPaths` syntax
   * (`id`, `data.created`, `items[0].id`). With `sse`, they apply to each event's payload.
   */
  jsonIgnore?: string[];
  /** Compare the body as its Server-Sent Events `data:` payloads, ignoring chunk boundaries. */
  sse?: boolean;
  /** Largest absolute difference between two JSON numbers that still counts as equal. */
  floatTolerance?: number;
}

/** Receives `(recorded, live)` and returns both normalized, for what `Compare` cannot express. */
export type BeforeCompareResponse = (
  recorded: HttpResponse,
  live: HttpResponse,
) => [HttpResponse, HttpResponse];

/** Throw `ResponseMismatchError` with a unified diff when `live` differs from `recorded`. */
export function compareResponses(
  compare: Compare,
  recorded: HttpResponse,
  live: HttpResponse,
  label: string,
): void {
  const before = normalize(compare, recorded);
  const after = normalize(compare, live);
  after.body = tolerate(before.body, after.body, compare.floatTolerance ?? 0);
  const expected = render(before);
  const actual = render(after);
  if (expected.join("\n") === actual.join("\n")) return;
  throw new ResponseMismatchError(
    [label, "--- recorded", "+++ live", ...unifiedDiff(expected, actual)].join("\n"),
  );
}

interface Normalized {
  status: number;
  headers: [string, string[]][];
  body: unknown;
}

function normalize(compare: Compare, response: HttpResponse): Normalized {
  const patterns = (compare.headers ?? []).map(glob);
  const headers = Object.entries(response.headers)
    .filter(([name]) => patterns.some((pattern) => pattern.test(name)))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const ignore = compare.jsonIgnore ?? [];
  const { type, content } = response.body;
  let body = content;
  if (type === "json") body = dropPaths(content, ignore, "");
  else if (compare.sse && type === "text") {
    body = sseEvents(String(content)).map((event) => dropPaths(event, ignore, ""));
  }
  return { status: response.status, headers, body };
}

function glob(pattern: string): RegExp {
  const source = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  return new RegExp(`^${source}$`, "i");
}

function sseEvents(text: string): unknown[] {
  const events: unknown[] = [];
  for (const block of text.replace(/\r\n/g, "\n").split("\n\n")) {
    const lines = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""));
    if (lines.length === 0) continue;
    const data = lines.join("\n");
    try {
      events.push(JSON.parse(data));
    } catch {
      events.push(data);
    }
  }
  return events;
}

function dropPaths(value: unknown, paths: string[], current: string): unknown {
  if (Array.isArray(value))
    return value.map((item, i) => dropPaths(item, paths, `${current}[${i}]`));
  if (isObject(value)) {
    const prefix = current ? `${current}.` : "";
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !paths.includes(prefix + key))
        .map(([key, item]) => [key, dropPaths(item, paths, prefix + key)]),
    );
  }
  return value;
}

/** `live` with numbers within `tolerance` of their recording set to it, so they leave the diff. */
function tolerate(recorded: unknown, live: unknown, tolerance: number): unknown {
  if (Array.isArray(recorded) && Array.isArray(live)) {
    return live.map((item, i) =>
      i < recorded.length ? tolerate(recorded[i], item, tolerance) : item,
    );
  }
  if (isObject(recorded) && isObject(live)) {
    return Object.fromEntries(
      Object.entries(live).map(([key, item]) => [
        key,
        key in recorded ? tolerate(recorded[key], item, tolerance) : item,
      ]),
    );
  }
  if (
    typeof recorded === "number" &&
    typeof live === "number" &&
    Math.abs(recorded - live) <= tolerance
  ) {
    return recorded;
  }
  return live;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function render({ status, headers, body }: Normalized): string[] {
  const lines = [`status: ${status}`, "@@ headers @@"];
  for (const [name, values] of headers) lines.push(...values.map((value) => `${name}: ${value}`));
  lines.push("@@ body @@");
  if (typeof body === "string") lines.push(...body.split(/\r?\n/));
  else if (body !== undefined) lines.push(...JSON.stringify(sortKeys(body), null, 2).split("\n"));
  return lines;
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (isObject(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortKeys(value[key])]),
    );
  }
  return value;
}

const CONTEXT = 3;

/** Hunks of a unified diff from `a` to `b`, without the `---`/`+++` header. */
function unifiedDiff(a: string[], b: string[]): string[] {
  // Trimming the common ends keeps the quadratic LCS table to the part that changed.
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let end = 0;
  while (
    end < a.length - start &&
    end < b.length - start &&
    a[a.length - 1 - end] === b[b.length - 1 - end]
  )
    end++;
  const x = a.slice(start, a.length - end);
  const y = b.slice(start, b.length - end);

  const lcs = Array.from({ length: x.length + 1 }, () =>
    Array.from({ length: y.length + 1 }, () => 0),
  );
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const ops: [" " | "-" | "+", string][] = a.slice(0, start).map((line) => [" ", line]);
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) {
      ops.push([" ", x[i++]]);
      j++;
    } else if (i < x.length && (j === y.length || lcs[i + 1][j] >= lcs[i][j + 1])) {
      ops.push(["-", x[i++]]);
    } else {
      ops.push(["+", y[j++]]);
    }
  }
  ops.push(...a.slice(a.length - end).map((line): [" ", string] => [" ", line]));

  const out: string[] = [];
  const changes = ops.flatMap(([op], index) => (op === " " ? [] : [index]));
  let k = 0;
  while (k < changes.length) {
    let last = k;
    while (last + 1 < changes.length && changes[last + 1] - changes[last] <= 2 * CONTEXT) last++;
    const from = Math.max(0, changes[k] - CONTEXT);
    const to = Math.min(ops.length, changes[last] + CONTEXT + 1);
    const before = ops.slice(0, from);
    const hunk = ops.slice(from, to);
    const aStart = before.filter(([op]) => op !== "+").length + 1;
    const bStart = before.filter(([op]) => op !== "-").length + 1;
    const aLen = hunk.filter(([op]) => op !== "+").length;
    const bLen = hunk.filter(([op]) => op !== "-").length;
    out.push(`@@ -${aStart},${aLen} +${bStart},${bLen} @@`, ...hunk.map(([op, line]) => op + line));
    k = last + 1;
  }
  return out;
}
