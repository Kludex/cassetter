/**
 * Intercepts the global `fetch` to record and replay HTTP traffic.
 */

import { NoMatchError, type Cassette } from "../cassette.js";
import { bodyToBuffer, type HeaderMap, type HttpResponse } from "../types.js";
import { isLocalhost, type Interceptor } from "./base.js";

type FetchPatch = {
  active: boolean;
  previous: typeof globalThis.fetch;
};

const FETCH_PATCHES = new WeakMap<typeof globalThis.fetch, FetchPatch>();

function activeFetch(candidate: typeof globalThis.fetch): typeof globalThis.fetch {
  let current = candidate;
  let patch = FETCH_PATCHES.get(current);
  while (patch && !patch.active) {
    current = patch.previous;
    patch = FETCH_PATCHES.get(current);
  }
  return current;
}

export class FetchInterceptor implements Interceptor {
  private _patched: typeof globalThis.fetch | null = null;

  /** Replace the global `fetch` with one backed by `cassette`. */
  install(cassette: Cassette): void {
    const patch: FetchPatch = {
      active: true,
      previous: globalThis.fetch,
    };

    const patched = async (
      input: string | URL | Request,
      init?: RequestInit,
    ): Promise<Response> => {
      if (!patch.active) {
        return activeFetch(patch.previous)(input, init);
      }

      const request = new Request(input, init);
      const { method, url: uri } = request;

      if (cassette.ignoreLocalhost && isLocalhost(uri)) {
        return patch.previous(input, init);
      }

      const headers = extractHeaders(request.headers);
      const requestBody =
        method === "GET" || method === "HEAD"
          ? null
          : Buffer.from(await request.clone().arrayBuffer());

      try {
        return buildResponse(cassette.play(method, uri, headers, requestBody));
      } catch (e) {
        if (!(e instanceof NoMatchError) || !cassette.canRecord) throw e;
      }

      // Claim the slot before going out: under concurrency the responses come
      // back in whatever order they finish, and recording in that order would
      // write a different cassette on every run.
      const order = cassette.reserveRecordOrder();

      const real = await patch.previous(request.clone());
      const responseBody = Buffer.from(await real.clone().arrayBuffer());

      cassette.record(
        method,
        uri,
        headers,
        requestBody,
        real.status,
        // `arrayBuffer()` hands back decoded bytes while the upstream encoding
        // and length headers describe the compressed representation.
        extractDecodedResponseHeaders(real.headers),
        responseBody,
        order,
      );

      return real;
    };

    FETCH_PATCHES.set(patched, patch);
    this._patched = patched;
    globalThis.fetch = patched;
  }

  /** Put the previous active `fetch` back if this interceptor owns the global. */
  uninstall(): void {
    if (!this._patched) return;

    const patch = FETCH_PATCHES.get(this._patched);
    if (patch) {
      patch.active = false;
      if (globalThis.fetch === this._patched) {
        globalThis.fetch = activeFetch(patch.previous);
      }
    }
    this._patched = null;
  }
}

function extractDecodedResponseHeaders(headers: Headers): HeaderMap {
  const out = extractHeaders(headers);
  delete out["content-encoding"];
  delete out["content-length"];
  return out;
}

/** Collect a `Headers` into name-to-values, lowercasing names. */
function extractHeaders(headers: Headers): HeaderMap {
  const out: HeaderMap = {};
  headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    (out[lower] ??= []).push(value);
  });
  return out;
}

/** Turn a recorded response back into a `Response`. */
function buildResponse(response: HttpResponse): Response {
  const headers: [string, string][] = [];
  for (const [key, values] of Object.entries(response.headers)) {
    for (const value of values) {
      headers.push([key, value]);
    }
  }

  // 204/304 must not carry a body.
  const body =
    response.status === 204 || response.status === 304
      ? null
      : bodyToBuffer(response.body);

  return new Response(body, { status: response.status, headers });
}
