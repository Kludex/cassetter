/**
 * Intercepts `node:http` and `node:https` to record and replay HTTP traffic.
 *
 * This covers clients that never touch the global `fetch`: `node-fetch`
 * (and so `gaxios` and the Google Cloud clients), `axios`, `got`, and anything
 * else built on `http.request`.
 */

import http from "node:http";
import https from "node:https";
import { syncBuiltinESMExports } from "node:module";
import { Readable, Transform, Writable, addAbortSignal, pipeline } from "node:stream";

import { NoMatchError, type Cassette } from "../cassette.js";
import { bodyToBuffer, type HeaderMap } from "../types.js";
import { isLocalhost, liveRequests, type Interceptor } from "./base.js";

type RequestFn = (...args: unknown[]) => http.ClientRequest;
type Module = Record<"request" | "get", RequestFn>;

type Patch = {
  active: boolean;
  previous: RequestFn;
};

const PATCHES = new WeakMap<RequestFn, Patch>();

const TARGETS: [Module, string][] = [
  [http as unknown as Module, "http:"],
  [https as unknown as Module, "https:"],
];

function activeRequest(candidate: RequestFn): RequestFn {
  let current = candidate;
  let patch = PATCHES.get(current);
  while (patch && !patch.active) {
    current = patch.previous;
    patch = PATCHES.get(current);
  }
  return current;
}

export class HttpInterceptor implements Interceptor {
  private _patched: [Module, "request" | "get", RequestFn][] = [];

  /** Replace `request` and `get` on `node:http` and `node:https` with ones backed by `cassette`. */
  install(cassette: Cassette): void {
    for (const [module, defaultProtocol] of TARGETS) {
      const requestPatch: Patch = { active: true, previous: module.request };
      const getPatch: Patch = { active: true, previous: module.get };

      const request: RequestFn = (...args) => {
        if (!requestPatch.active) return activeRequest(requestPatch.previous)(...args);
        const live = activeRequest(requestPatch.previous);
        const { url, options, callback } = parseArgs(defaultProtocol, args);
        if (liveRequests.getStore() || (cassette.ignoreLocalhost && isLocalhost(url)) || isTunnel(options)) {
          return live(...args);
        }
        return new CassetteRequest(cassette, live, args, url, options, callback) as unknown as http.ClientRequest;
      };
      const get: RequestFn = (...args) => {
        if (!getPatch.active) return activeRequest(getPatch.previous)(...args);
        const req = request(...args);
        req.end();
        return req;
      };

      PATCHES.set(request, requestPatch);
      PATCHES.set(get, getPatch);
      module.request = request;
      module.get = get;
      this._patched.push([module, "request", request], [module, "get", get]);
    }
    syncBuiltinESMExports();
  }

  /** Put the previous active functions back where this interceptor still owns them. */
  uninstall(): void {
    for (const [module, key, patched] of this._patched) {
      const patch = PATCHES.get(patched)!;
      patch.active = false;
      if (module[key] === patched) {
        module[key] = activeRequest(patch.previous);
      }
    }
    this._patched = [];
    syncBuiltinESMExports();
  }
}

/** A stand-in `ClientRequest` that buffers the body and answers from the cassette. */
class CassetteRequest extends Writable {
  readonly method: string;
  readonly path: string;
  private readonly _headers: Record<string, string | string[]> = {};
  private readonly _chunks: Buffer[] = [];
  private _timeout: number | null = null;
  private _inflight: http.ClientRequest | null = null;

  constructor(
    private readonly _cassette: Cassette,
    private readonly _live: RequestFn,
    private readonly _args: unknown[],
    private readonly _url: string,
    options: http.RequestOptions,
    callback: ((res: http.IncomingMessage) => void) | undefined,
  ) {
    super({ autoDestroy: false });
    this.method = (options.method ?? "GET").toUpperCase();
    this.path = options.path ?? "/";
    const headers = options.headers ?? {};
    const entries: [string, unknown][] = [];
    if (Array.isArray(headers)) {
      for (let i = 0; i < headers.length; i += 2) entries.push([headers[i], headers[i + 1]]);
    } else {
      entries.push(...Object.entries(headers));
    }
    for (const [key, value] of entries) {
      if (value === undefined) continue;
      const previous = this.getHeader(key);
      this.setHeader(key, previous === undefined ? (value as string) : [previous, value as string].flat().map(String));
    }
    if (callback) this.once("response", callback);
    if (options.signal) addAbortSignal(options.signal, this);
  }

  setHeader(name: string, value: number | string | readonly string[]): this {
    this._headers[name.toLowerCase()] = typeof value === "object" ? [...value] : String(value);
    return this;
  }

  getHeader(name: string): string | string[] | undefined {
    return this._headers[name.toLowerCase()];
  }

  getHeaders(): Record<string, string | string[]> {
    return { ...this._headers };
  }

  hasHeader(name: string): boolean {
    return name.toLowerCase() in this._headers;
  }

  removeHeader(name: string): void {
    delete this._headers[name.toLowerCase()];
  }

  setTimeout(ms: number, callback?: () => void): this {
    this._timeout = ms;
    this._inflight?.setTimeout(ms);
    if (callback) this.once("timeout", callback);
    return this;
  }

  setNoDelay(): void {}

  setSocketKeepAlive(): void {}

  flushHeaders(): void {}

  abort(): void {
    this.destroy();
  }

  override _write(chunk: Buffer, _encoding: BufferEncoding, done: () => void): void {
    this._chunks.push(chunk);
    done();
  }

  override _destroy(error: Error | null, done: (error?: Error | null) => void): void {
    this._inflight?.destroy(error ?? undefined);
    done(error);
  }

  override _final(done: () => void): void {
    done();
    this._respond().catch((error: Error) => this.destroy(error));
  }

  private async _respond(): Promise<void> {
    const cassette = this._cassette;
    const headers: HeaderMap = {};
    for (const [key, value] of Object.entries(this._headers)) {
      headers[key] = typeof value === "string" ? [value] : value;
    }
    const body = Buffer.concat(this._chunks);

    try {
      const recorded = cassette.play(this.method, this._url, headers, body);
      const replayed = bodyToBuffer(recorded.body);
      return this._emitResponse(
        recorded.status,
        recorded.headers,
        Readable.from(replayed.length ? [replayed] : [], { objectMode: false }),
      );
    } catch (e) {
      if (!(e instanceof NoMatchError) || !cassette.canRecord) throw e;
    }

    // Claim the slot before going out, so concurrent recordings keep a stable order.
    const order = cassette.reserveRecordOrder();
    const real = await this._sendLive(body);
    const responseHeaders: HeaderMap = {};
    for (let i = 0; i < real.rawHeaders.length; i += 2) {
      (responseHeaders[real.rawHeaders[i].toLowerCase()] ??= []).push(real.rawHeaders[i + 1]);
    }
    const status = real.statusCode ?? 200;
    const chunks: Buffer[] = [];
    const tap = new Transform({
      transform(chunk: Buffer, _encoding, next) {
        chunks.push(chunk);
        next(null, chunk);
      },
      flush: (next) => {
        this._inflight = null;
        cassette.record(this.method, this._url, headers, body, status, responseHeaders, Buffer.concat(chunks), order);
        next();
      },
    });
    pipeline(real, tap, () => {});
    this._emitResponse(status, responseHeaders, tap);
  }

  private _sendLive(body: Buffer): Promise<http.IncomingMessage> {
    const [first, second] = this._args;
    const req = (this._inflight = liveRequests.run(true, () =>
      typeof first === "string" || first instanceof URL
        ? this._live(first, { ...(typeof second === "object" ? second : {}), headers: this._headers })
        : this._live({ ...(first as http.RequestOptions), headers: this._headers }),
    ));
    if (this._timeout !== null) req.setTimeout(this._timeout);
    req.on("timeout", () => this.emit("timeout"));
    return new Promise((resolve, reject) => {
      req.once("response", resolve);
      req.once("error", reject);
      req.end(body);
    });
  }

  private _emitResponse(status: number, headers: HeaderMap, body: Readable): void {
    const rawHeaders: string[] = [];
    const joined: http.IncomingHttpHeaders = {};
    for (const [key, values] of Object.entries(headers)) {
      for (const value of values) rawHeaders.push(key, value);
      joined[key.toLowerCase()] = key.toLowerCase() === "set-cookie" ? values : values.join(", ");
    }

    const response = Object.assign(body, {
      statusCode: status,
      statusMessage: http.STATUS_CODES[status] ?? "",
      httpVersion: "1.1",
      httpVersionMajor: 1,
      httpVersionMinor: 1,
      headers: joined,
      rawHeaders,
      trailers: {},
      rawTrailers: [],
      complete: true,
      req: this,
    });
    response.once("end", () => this.destroy());
    this.emit("response", response);
  }
}

/** Resolve `http.request`'s overloaded arguments into a URL, options, and callback. */
function parseArgs(
  defaultProtocol: string,
  args: unknown[],
): { url: string; options: http.RequestOptions; callback?: (res: http.IncomingMessage) => void } {
  const [first, second, third] = args;
  const base = typeof first === "string" || first instanceof URL ? new URL(first) : null;
  const options = ((base ? (typeof second === "object" ? second : {}) : first) ?? {}) as http.RequestOptions;
  const callback = [second, third].find((arg) => typeof arg === "function") as
    | ((res: http.IncomingMessage) => void)
    | undefined;

  const url = base ?? new URL(`${defaultProtocol}//localhost`);
  if (options.protocol) url.protocol = options.protocol;
  const host = options.hostname ?? options.host;
  if (host) url.hostname = host;
  if (options.port) url.port = String(options.port);
  const path = options.path ?? (base ? `${base.pathname}${base.search}` : "/");
  return {
    url: `${url.protocol}//${url.host}${path}`,
    options: { ...options, path },
    callback,
  };
}

/** `CONNECT`, upgrades, and `Expect: 100-continue` trade data before or instead of a response, so they go live. */
function isTunnel(options: http.RequestOptions): boolean {
  const headers = options.headers ?? {};
  const names = Array.isArray(headers) ? headers.filter((_, i) => i % 2 === 0) : Object.keys(headers);
  return options.method?.toUpperCase() === "CONNECT" || names.some((name) => /^(upgrade|expect)$/i.test(name));
}
