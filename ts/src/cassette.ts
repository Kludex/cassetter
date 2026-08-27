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

export class CassetteNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CassetteNotFoundError";
  }
}

export class CassetteLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CassetteLoadError";
  }
}

export class CassetteExpiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CassetteExpiredError";
  }
}

export class NoMatchError extends Error {
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
  /** `once` replays without recording when the cassette already existed. */
  private _onceReplayOnly = false;
  /** Mode of the cassette `rewrite` deleted, to put back on its replacement. */
  private _rewrittenFileMode: number | null = null;

  constructor(path: string, options: CassetteOptions = {}) {
    this._path = path;
    this._recordMode = options.recordMode ?? RecordMode.ONCE;
    this._matchConfig = options.matchConfig ?? {};
    this._securityConfig = options.securityConfig ?? {};
    this._maxAge = options.maxAge ? parseDuration(options.maxAge) : null;
    this._onExpiry = options.onExpiry ?? "warn";
    this._ignoreLocalhost = options.ignoreLocalhost ?? false;
  }

  get path(): string {
    return this._path;
  }

  get recordMode(): RecordMode {
    return this._recordMode;
  }

  get ignoreLocalhost(): boolean {
    return this._ignoreLocalhost;
  }

  get interactions(): HttpInteraction[] {
    return this._inner ? this._inner.interactions : [];
  }

  get grpcInteractions(): GrpcInteraction[] {
    return this._inner ? this._inner.grpcInteractions : [];
  }

  get wsInteractions(): WsInteraction[] {
    return this._inner ? this._inner.wsInteractions : [];
  }

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

  play(
    method: string,
    uri: string,
    headers: HeaderMap,
    body: Buffer | null,
  ): HttpResponse {
    if (!this._inner) {
      throw new NoMatchError("cassette not loaded");
    }

    const processed = processBody(
      body ?? Buffer.alloc(0),
      getHeader(headers, "content-type"),
      getHeader(headers, "content-encoding"),
    );

    const hit = this._inner.takeMatch(
      { method, uri, headers, body: processed },
      this._matchConfig,
    );

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

    const interaction = scrubInteraction(
      {
        request: { method, uri, headers: requestHeaders, body: reqBody },
        response: { status, headers: cleanRespHeaders, body: respBody },
        recordedAt: new Date().toISOString(),
      },
      this._securityConfig,
    );

    this._ensureInner().addInteraction(interaction);
    this._recordOrders.push(this._recordOrders.length);
    this._dirty = true;
    return interaction.response;
  }

  // --- gRPC ---

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

  playWs(uri: string): WsInteraction {
    if (!this._inner) {
      throw new NoMatchError("cassette not loaded");
    }
    const hit = this._inner.takeWsMatch(uri);
    if (hit === null) {
      throw new NoMatchError(`no matching WebSocket interaction for ${uri}`);
    }
    return hit.interaction;
  }

  recordWs(uri: string, headers: HeaderMap, frames: WsFrame[]): void {
    const interaction = scrubWsInteraction(
      { uri, headers, frames, recordedAt: new Date().toISOString() },
      this._securityConfig,
    );
    this._ensureInner().addWsInteraction(interaction);
    this._dirty = true;
  }

  // --- Internals ---

  private _ensureInner(): NativeCassette {
    this._inner ??= new native.Cassette();
    return this._inner;
  }

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
