/**
 * Data shapes exchanged with the native core.
 *
 * These mirror the cassette file format one-to-one, so what you see here is
 * what is written to disk and what the Python binding produces. Binary bodies
 * are hex strings (as in the file); use `bodyToBuffer` / `binaryBody` to move
 * between hex and `Buffer`.
 */

export type BodyType = "json" | "text" | "binary" | "none";

/** The matchers a `MatchConfig` may name. */
export type Matcher = "method" | "uri" | "headers" | "body" | "json_body";

export interface Body {
  type: BodyType;
  /** Parsed JSON for `json`, the string for `text`, hex for `binary`. */
  content?: unknown;
}

export type HeaderMap = Record<string, string[]>;

export interface HttpRequest {
  method: string;
  uri: string;
  headers: HeaderMap;
  body: Body;
}

export interface HttpResponse {
  status: number;
  headers: HeaderMap;
  body: Body;
}

export interface HttpInteraction {
  request: HttpRequest;
  response: HttpResponse;
  recordedAt: string;
}

export interface GrpcRequest {
  method: string;
  metadata: HeaderMap;
  body: Body;
}

export interface GrpcResponse {
  statusCode: number;
  statusMessage: string;
  metadata: HeaderMap;
  body: Body;
}

export interface GrpcInteraction {
  request: GrpcRequest;
  response: GrpcResponse;
  recordedAt: string;
  jsonDebug?: unknown;
}

export interface WsFrame {
  direction: "send" | "recv";
  frameType: "text" | "binary";
  body: Body;
  offsetMs: number;
}

export interface WsInteraction {
  uri: string;
  headers: HeaderMap;
  frames: WsFrame[];
  recordedAt: string;
}

/** Fields to match a request on. Defaults to `["method", "uri"]`. */
export interface MatchConfig {
  matchOn?: Matcher[];
  ignoreJsonPaths?: string[];
}

/**
 * Security filtering.
 *
 * Each list **adds to** the built-in defaults rather than standing in for
 * them, so naming one more header to scrub never starts recording the ones
 * already covered. Read the built-ins with `defaultFilterHeaders()` and
 * friends.
 */
export interface SecurityConfig {
  filterHeaders?: string[];
  filterQueryParameters?: string[];
  bodyScrubPatterns?: string[];
  replacement?: string;
}

export interface CassetteConfig extends MatchConfig, SecurityConfig {
  recordMode?: string;
  intercept?: string[];
  maxAge?: string;
  onExpiry?: "warn" | "fail" | "rerecord";
  ignoreLocalhost?: boolean;
}

// --- Body helpers ---

export const NONE_BODY: Body = { type: "none" };

/** Decode a body into raw bytes, whatever its type. */
export function bodyToBuffer(body: Body): Buffer {
  switch (body.type) {
    case "json":
      return Buffer.from(JSON.stringify(body.content ?? null));
    case "text":
      return Buffer.from(String(body.content ?? ""));
    case "binary":
      return Buffer.from(String(body.content ?? ""), "hex");
    default:
      return Buffer.alloc(0);
  }
}

/** Build a binary body from raw bytes (stored as hex, as in the cassette). */
export function binaryBody(buf: Buffer): Body {
  return { type: "binary", content: buf.toString("hex") };
}

/** Read a binary body's bytes. Throws if the body is not binary. */
export function binaryBodyBytes(body: Body): Buffer {
  if (body.type !== "binary") {
    throw new TypeError(`expected a binary body, got '${body.type}'`);
  }
  return Buffer.from(String(body.content ?? ""), "hex");
}
