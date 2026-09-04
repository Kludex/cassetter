/**
 * Record/replay orchestration over the native cassette core.
 *
 * The cassette format, request matching, security filtering, and body
 * processing all live in Rust (`cassetter-core`). This file is the thin,
 * idiomatic layer on top - the same role `src/cassetter/cassette.py` plays for
 * the Python binding.
 */

import { existsSync, rmSync, statSync } from "node:fs";

import { native, processBody, scrubInteraction, scrubGrpcInteraction, scrubWsInteraction } from "./binding.js";
import type { NativeCassette } from "./binding.js";
import { DISCARDING_MODES, RecordMode, parseDuration } from "./recording.js";
import { NONE_BODY, bodyToBuffer } from "./types.js";
import type {
  Body,
  GrpcInteraction,
  GrpcResponse,
  HeaderMap,
  HttpInteraction,
  HttpResponse,
  MatchConfig,
  SecurityConfig,
  WsFrame,
  WsInteraction,
} from "./types.js";

// --- Errors ---

/** Raised when a cassette file is required but absent. */
export class CassetteNotFoundError extends Error {
  /** Configure a cassette. Nothing is read until `load()`. */
  constructor(message: string) {
    super(message);
    this.name = "CassetteNotFoundError";
  }
}

/** Raised when a cassette exists but cannot be parsed. */
export class CassetteLoadError extends Error {
  /** Configure a cassette. Nothing is read until `load()`. */
  constructor(message: string) {
    super(message);
    this.name = "CassetteLoadError";
  }
}

/** Raised when a cassette is older than `maxAge` and `onExpiry` is `fail`. */
export class CassetteExpiredError extends Error {
  /** Configure a cassette. Nothing is read until `load()`. */
  constructor(message: string) {
    super(message);
    this.name = "CassetteExpiredError";
  }
}

/** Raised when no recorded interaction matches, and none may be recorded. */
export class NoMatchError extends Error {
  /** Configure a cassette. Nothing is read until `load()`. */
  constructor(message: string) {
    super(message);
    this.name = "NoMatchError";
  }
}

export interface CassetteOptions {
  recordMode?: RecordMode;
  matchConfig?: MatchConfig;
  securityConfig?: SecurityConfig;
  maxAge?: string;
  onExpiry?: "warn" | "fail" | "rerecord";
  ignoreLocalhost?: boolean;
}

export class Cassette {
  private readonly _path: string;
  private readonly _recordMode: RecordMode;
  private readonly _matchConfig: MatchConfig;
  private readonly _securityConfig: SecurityConfig;
  private readonly _maxAge: number | null;
  private readonly _onExpiry: "warn" | "fail" | "rerecord";
  private readonly _ignoreLocalhost: boolean;

  private _inner: NativeCassette | null = null;
  private _dirty = false;
  /** Order interactions were recorded in, to break ties in the output order. */
  private _recordOrders: number[] = [];
  /** Next position `reserveRecordOrder` will hand out. */
  private _nextRecordOrder = 0;
  /** `once` replays without recording when the cassette already existed. */
  private _onceReplayOnly = false;
  /** Mode of the cassette `rewrite` deleted, to put back on its replacement. */
  private _rewrittenFileMode: number | null = null;

  /** Configure a cassette. Nothing is read until `load()`. */
  constructor(path: string, options: CassetteOptions = {}) {
    this._path = path;
    this._recordMode = options.recordMode ?? RecordMode.ONCE;
    this._matchConfig = options.matchConfig ?? {};
    this._securityConfig = options.securityConfig ?? {};
    this._maxAge = options.maxAge ? parseDuration(options.maxAge) : null;
    this._onExpiry = options.onExpiry ?? "warn";
    this._ignoreLocalhost = options.ignoreLocalhost ?? false;
  }

  /** Where this cassette is read from and written to. */
  get path(): string {
    return this._path;
  }

  /** The record mode in force. */
  get recordMode(): RecordMode {
    return this._recordMode;
  }

  /** Whether localhost traffic bypasses the cassette entirely. */
  get ignoreLocalhost(): boolean {
    return this._ignoreLocalhost;
  }

  /** The recorded HTTP interactions, empty before `load()`. */
  get interactions(): HttpInteraction[] {
    return this._inner ? this._inner.interactions : [];
  }

  /** The recorded gRPC interactions, empty before `load()`. */
  get grpcInteractions(): GrpcInteraction[] {
    return this._inner ? this._inner.grpcInteractions : [];
  }

  /** The recorded WebSocket interactions, empty before `load()`. */
  get wsInteractions(): WsInteraction[] {
    return this._inner ? this._inner.wsInteractions : [];
  }

  /** Whether this mode may replay an existing interaction. */
  get canReplay(): boolean {
    return !DISCARDING_MODES.includes(this._recordMode);
  }

  /** Whether an unmatched request may go to the network and be recorded. */
  get canRecord(): boolean {
    if (
      this._recordMode === RecordMode.ALL ||
      this._recordMode === RecordMode.NEW_EPISODES ||
      this._recordMode === RecordMode.REWRITE
    ) {
      return true;
    }
    // `once` records only when the cassette didn't exist: with an existing
    // cassette an unmatched request must raise instead of silently hitting the
    // network and appending.
    return this._recordMode === RecordMode.ONCE && !this._onceReplayOnly;
  }

  /** Load from disk, or start an empty cassette based on the record mode. */
  load(): void {
    let exists = existsSync(this._path);

    // `rewrite` drops the file before recording, so a run that captures
    // nothing leaves no stale cassette behind. The writer copies the mode off
    // the file it replaces, so with nothing there it has to be handed over -
    // otherwise a 0600 cassette comes back at the process umask.
    if (this._recordMode === RecordMode.REWRITE && exists) {
      try {
        this._rewrittenFileMode = statSync(this._path).mode & 0o7777;
      } catch {
        this._rewrittenFileMode = null;
      }
      rmSync(this._path, { force: true });
      exists = false;
    }

    const discarding = DISCARDING_MODES.includes(this._recordMode);

    if (discarding || !exists) {
      this._inner = new native.Cassette();
      this._recordOrders = [];
      this._nextRecordOrder = 0;
      // Loading again onto the same object must not inherit the last load's
      // replay-only state: with no file there, `once` may record afresh.
      this._onceReplayOnly = false;
      if (discarding) {
        this._dirty = true;
      }
      return;
    }

    try {
      this._inner = native.Cassette.load(this._path);
    } catch (e) {
      throw new CassetteLoadError(
        `could not parse cassette ${this._path}: ${(e as Error).message}`,
      );
    }
    this._onceReplayOnly = true;
    this._recordOrders = this._inner.interactions.map((_, i) => i);
    this._nextRecordOrder = this._recordOrders.length;
    this._checkExpiry();
  }

  /**
   * Write to disk if modified.
   *
   * An empty cassette is written only when a file already exists, so a
   * re-record that captured nothing truncates the stale file instead of
   * leaving it behind. Interactions go out in a canonical order rather than
   * the order their responses arrived in, so a concurrent suite produces the
   * same file every run.
   */
  save(): void {
    if (!this._inner || !this._dirty) return;
    if (this._inner.length === 0 && !existsSync(this._path)) return;

    this._inner.save(
      this._path,
      this._inner.outputOrder(this._matchConfig, this._recordOrders),
      this._rewrittenFileMode ?? undefined,
    );
    this._dirty = false;
    this._rewrittenFileMode = null;
  }

  /** Serialize to YAML without touching the filesystem. */
  toYaml(): string {
    return this._inner ? this._inner.toYaml() : "";
  }

  /** Serialize to TOML without touching the filesystem. */
  toToml(): string {
    return this._inner ? this._inner.toToml() : "";
  }

  // --- HTTP ---

  /**
   * Claim this interaction's position before its request is issued.
   *
   * Interceptors record once the response is back, so under concurrency the
   * cassette would otherwise be written in whatever order responses arrived
   * in - different on every run.
   */
  reserveRecordOrder(): number {
    return this._nextRecordOrder++;
  }

  play(
    method: string,
    uri: string,
    headers: HeaderMap,
    body: Buffer | null,
  ): HttpResponse {
    if (!this._inner) {
      throw new NoMatchError("cassette not loaded");
    }
    if (!this.canReplay) {
      throw new NoMatchError(`replay disabled in ${this._recordMode} mode`);
    }

    const processed = processBody(
      body ?? Buffer.alloc(0),
      getHeader(headers, "content-type"),
      getHeader(headers, "content-encoding"),
    );

    // Interactions are scrubbed at write time, so the live request has to be
    // scrubbed with the same config before matching: a URI recorded as
    // api_key=[FILTERED] would otherwise never match the real query string,
    // and a scrubbed body field would never match the real one.
    const probe = scrubInteraction(
      {
        request: { method, uri, headers, body: processed },
        response: { status: 0, headers: {}, body: NONE_BODY },
        recordedAt: "",
      },
      this._securityConfig,
    ).request;

    const hit = this._inner.takeMatch(probe, this._matchConfig);

    if (hit === null) {
      throw new NoMatchError(`no matching interaction for ${method} ${uri}`);
    }
    return hit.interaction.response;
  }

  record(
    method: string,
    uri: string,
    requestHeaders: HeaderMap,
    requestBody: Buffer | null,
    status: number,
    responseHeaders: HeaderMap,
    responseBody: Buffer | null,
    order?: number,
  ): HttpResponse {
    const reqBody = processBody(
      requestBody ?? Buffer.alloc(0),
      getHeader(requestHeaders, "content-type"),
      getHeader(requestHeaders, "content-encoding"),
    );
    const respBody = processBody(
      responseBody ?? Buffer.alloc(0),
      getHeader(responseHeaders, "content-type"),
      getHeader(responseHeaders, "content-encoding"),
    );

    // The body is stored decompressed, so content-encoding must not survive.
    const cleanRespHeaders: HeaderMap = {};
    for (const [k, v] of Object.entries(responseHeaders)) {
      if (k.toLowerCase() !== "content-encoding") {
        cleanRespHeaders[k] = v;
      }
    }

    const interaction = retagContentLength(
      scrubInteraction(
        {
          request: { method, uri, headers: requestHeaders, body: reqBody },
          response: { status, headers: cleanRespHeaders, body: respBody },
          recordedAt: new Date().toISOString(),
        },
        this._securityConfig,
      ),
    );

    this._ensureInner().addInteraction(interaction);
    this._recordOrders.push(order ?? this.reserveRecordOrder());
    this._dirty = true;
    return interaction.response;
  }

  // --- gRPC ---

  /** Replay a gRPC response for `method`, or throw `NoMatchError`. */
  playGrpc(method: string): GrpcResponse {
    if (!this._inner) {
      throw new NoMatchError("cassette not loaded");
    }
    const hit = this._inner.takeGrpcMatch(method);
    if (hit === null) {
      throw new NoMatchError(`no matching gRPC interaction for ${method}`);
    }
    return hit.interaction.response;
  }

  recordGrpc(
    method: string,
    metadata: HeaderMap,
    requestBody: Body,
    responseBody: Body,
    options: {
      statusCode?: number;
      statusMessage?: string;
      responseMetadata?: HeaderMap;
      jsonDebug?: unknown;
    } = {},
  ): GrpcResponse {
    const interaction = scrubGrpcInteraction(
      {
        request: { method, metadata, body: requestBody },
        response: {
          statusCode: options.statusCode ?? 0,
          statusMessage: options.statusMessage ?? "OK",
          metadata: options.responseMetadata ?? {},
          body: responseBody,
        },
        recordedAt: new Date().toISOString(),
        jsonDebug: options.jsonDebug,
      },
      this._securityConfig,
    );

    this._ensureInner().addGrpcInteraction(interaction);
    this._dirty = true;
    return interaction.response;
  }

  // --- WebSocket ---

  /** Replay a WebSocket interaction for `uri`, or throw `NoMatchError`. */
  playWs(uri: string): WsInteraction {
    if (!this._inner) {
      throw new NoMatchError("cassette not loaded");
    }
    const probe = scrubWsInteraction(
      { uri, headers: {}, frames: [], recordedAt: "" },
      this._securityConfig,
    );
    const hit = this._inner.takeWsMatch(probe.uri);
    if (hit === null) {
      throw new NoMatchError(`no matching WebSocket interaction for ${uri}`);
    }
    return hit.interaction;
  }

  /** Record a WebSocket connection and its frames, scrubbed. */
  recordWs(uri: string, headers: HeaderMap, frames: WsFrame[]): void {
    const interaction = scrubWsInteraction(
      { uri, headers, frames, recordedAt: new Date().toISOString() },
      this._securityConfig,
    );
    this._ensureInner().addWsInteraction(interaction);
    this._dirty = true;
  }

  // --- Internals ---

  /** The native cassette, created on first use if `load()` never ran. */
  private _ensureInner(): NativeCassette {
    this._inner ??= new native.Cassette();
    return this._inner;
  }

  /** Apply `onExpiry` when the newest recording predates `maxAge`. */
  private _checkExpiry(): void {
    if (this._maxAge === null || !this._inner) return;

    const newest = this._newestRecordedAt();
    if (newest === null) return;
    if (newest.getTime() >= Date.now() - this._maxAge) return;

    const ageDays = Math.floor(
      (Date.now() - newest.getTime()) / (24 * 60 * 60 * 1000),
    );
    const msg = `cassette '${this._path}' is ${ageDays} days old (maxAge=${this._maxAge}ms)`;

    if (this._onExpiry === "fail") {
      throw new CassetteExpiredError(msg);
    }
    if (this._onExpiry === "rerecord") {
      this._inner = new native.Cassette();
      this._recordOrders = [];
      this._onceReplayOnly = false;
      this._dirty = true;
      return;
    }
    process.emitWarning(msg, "CassetteExpiredWarning");
  }

  /** The most recent `recordedAt` across every protocol, if any. */
  private _newestRecordedAt(): Date | null {
    if (!this._inner) return null;

    const stamps = [
      ...this._inner.interactions.map((i) => i.recordedAt),
      ...this._inner.grpcInteractions.map((i) => i.recordedAt),
      ...this._inner.wsInteractions.map((i) => i.recordedAt),
    ].filter(Boolean);

    if (stamps.length === 0) return null;

    return stamps.reduce<Date | null>((newest, ts) => {
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return newest;
      return newest === null || d > newest ? d : newest;
    }, null);
  }
}

/**
 * Restate a response's `content-length` for the body as recorded.
 *
 * Decompressing a response and scrubbing a secret out of a body both change
 * its length, and a client that checks the header against what it reads fails
 * on replay when the two disagree.
 *
 * Only the response, and only when it carries a body. A request's header is
 * compared against the incoming one by the `headers` matcher, so rewriting it
 * would stop an identical request from replaying; and on a HEAD or 304 the
 * header describes a representation that was never sent, so there is no body
 * to measure it against.
 */
function retagContentLength(interaction: HttpInteraction): HttpInteraction {
  const served = bodyToBuffer(interaction.response.body);
  if (served.length === 0) return interaction;

  const length = String(served.length);
  let changed = false;
  const headers: HeaderMap = {};
  for (const [key, values] of Object.entries(interaction.response.headers)) {
    if (key.toLowerCase() === "content-length") {
      if (values.length !== 1 || values[0] !== length) changed = true;
      headers[key] = [length];
    } else {
      headers[key] = values;
    }
  }
  if (!changed) return interaction;

  return {
    ...interaction,
    response: { ...interaction.response, headers },
  };
}

/** Case-insensitive header lookup returning the first value. */
export function getHeader(headers: HeaderMap, name: string): string | null {
  const target = name.toLowerCase();
  for (const [key, values] of Object.entries(headers)) {
    if (key.toLowerCase() === target && values.length > 0) {
      return values[0];
    }
  }
  return null;
}
