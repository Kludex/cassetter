/**
 * Intercepts the global `fetch` to record and replay HTTP traffic.
 */

import { NoMatchError, type Cassette } from "../cassette.js";
import { bodyToBuffer, type HeaderMap, type HttpResponse } from "../types.js";
import { isLocalhost, type Interceptor } from "./base.js";

export class FetchInterceptor implements Interceptor {
  private _cassette: Cassette | null = null;
  private _originalFetch: typeof globalThis.fetch | null = null;

  install(cassette: Cassette): void {
    this._cassette = cassette;
    this._originalFetch = globalThis.fetch;

    const originalFetch = this._originalFetch;

    globalThis.fetch = async (
      input: string | URL | Request,
      init?: RequestInit,
    ): Promise<Response> => {
      const request = new Request(input, init);
      const { method, url: uri } = request;

      if (cassette.ignoreLocalhost && isLocalhost(uri)) {
        return originalFetch(input, init);
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

      const real = await originalFetch(request.clone());
      const responseBody = Buffer.from(await real.clone().arrayBuffer());

      cassette.record(
        method,
        uri,
        headers,
        requestBody,
        real.status,
        // `arrayBuffer()` hands back decoded bytes while the upstream
        // content-encoding header survives on the response. Passing it through
        // would have the recorder try to decompress what is already plain.
        extractHeadersSkipEncoding(real.headers),
        responseBody,
        order,
      );

      return real;
    };
  }

  uninstall(): void {
    if (this._originalFetch) {
      globalThis.fetch = this._originalFetch;
      this._originalFetch = null;
    }
    this._cassette = null;
  }
}

function extractHeadersSkipEncoding(headers: Headers): HeaderMap {
  const out = extractHeaders(headers);
  delete out["content-encoding"];
  return out;
}

function extractHeaders(headers: Headers): HeaderMap {
  const out: HeaderMap = {};
  headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    (out[lower] ??= []).push(value);
  });
  return out;
}

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
