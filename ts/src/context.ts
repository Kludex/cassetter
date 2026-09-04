/**
 * `useCassette` - the main entry point for recording/replaying HTTP traffic.
 *
 * @example
 * ```ts
 * await useCassette("tests/cassettes/users.yaml", async () => {
 *   const res = await fetch("https://api.example.com/users");
 * });
 * ```
 */

import { Cassette } from "./cassette.js";
import { FetchInterceptor } from "./intercept/fetch.js";
import type { Interceptor } from "./intercept/base.js";
import { RecordMode, parseRecordMode } from "./recording.js";
import type { CassetteConfig } from "./types.js";

export type UseCassetteOptions = CassetteConfig;

const INTERCEPTORS: Record<string, () => Interceptor> = {
  fetch: () => new FetchInterceptor(),
};

/**
 * Record or replay every `fetch` made inside `fn`.
 *
 * Interceptors are installed before the callback and removed after it, even
 * if it throws; the cassette is written on the way out.
 */
export async function useCassette(
  path: string,
  fn: (cassette: Cassette) => Promise<void> | void,
): Promise<Cassette>;
export async function useCassette(
  path: string,
  options: UseCassetteOptions,
  fn: (cassette: Cassette) => Promise<void> | void,
): Promise<Cassette>;
export async function useCassette(
  path: string,
  optionsOrFn:
    | UseCassetteOptions
    | ((cassette: Cassette) => Promise<void> | void),
  maybeFn?: (cassette: Cassette) => Promise<void> | void,
): Promise<Cassette> {
  const options: UseCassetteOptions =
    typeof optionsOrFn === "function" ? {} : optionsOrFn;
  const fn = typeof optionsOrFn === "function" ? optionsOrFn : maybeFn;

  if (!fn) {
    throw new TypeError("useCassette requires a callback");
  }

  const cassette = new Cassette(path, {
    recordMode: options.recordMode
      ? parseRecordMode(options.recordMode)
      : RecordMode.ONCE,
    matchConfig: {
      matchOn: options.matchOn,
      ignoreJsonPaths: options.ignoreJsonPaths,
    },
    securityConfig: {
      filterHeaders: options.filterHeaders,
      filterQueryParameters: options.filterQueryParameters,
      bodyScrubPatterns: options.bodyScrubPatterns,
      replacement: options.replacement,
    },
    maxAge: options.maxAge,
    onExpiry: options.onExpiry,
    ignoreLocalhost: options.ignoreLocalhost,
  });

  cassette.load();

  const interceptors = resolveInterceptors(options.intercept);
  for (const interceptor of interceptors) {
    interceptor.install(cassette);
  }

  try {
    await fn(cassette);
  } finally {
    for (const interceptor of [...interceptors].reverse()) {
      interceptor.uninstall();
    }
    cassette.save();
  }

  return cassette;
}

/** Instantiate the named interceptors, or the default set. */
function resolveInterceptors(names?: string[]): Interceptor[] {
  if (!names || names.length === 0) {
    return [new FetchInterceptor()];
  }
  return names.map((name) => {
    const factory = INTERCEPTORS[name];
    if (!factory) {
      throw new Error(
        `unknown interceptor: '${name}' (available: ${Object.keys(INTERCEPTORS).join(", ")})`,
      );
    }
    return factory();
  });
}
