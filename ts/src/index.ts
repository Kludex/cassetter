/**
 * cassetter - HTTP cassette recorder for Node.js tests. Safe by default.
 *
 * Cassette format, request matching, security filtering, and body processing
 * are implemented in Rust (`cassetter-core`) and shared with the Python
 * binding, so cassettes are interchangeable between the two.
 *
 * @example
 * ```ts
 * import { useCassette } from "cassetter";
 *
 * await useCassette("tests/cassettes/users.yaml", async () => {
 *   const res = await fetch("https://api.example.com/users");
 *   console.log(res.status);
 * });
 * ```
 */

export { useCassette } from "./context.js";
export type { UseCassetteOptions } from "./context.js";

export {
  Cassette,
  CassetteExpiredError,
  CassetteLoadError,
  CassetteNotFoundError,
  NoMatchError,
  getHeader,
} from "./cassette.js";
export type { CassetteOptions } from "./cassette.js";

export {
  DISCARDING_MODES,
  RecordMode,
  parseDuration,
  parseRecordMode,
} from "./recording.js";

export {
  NONE_BODY,
  binaryBody,
  binaryBodyBytes,
  bodyToBuffer,
} from "./types.js";
export type {
  Body,
  BodyType,
  CassetteConfig,
  GrpcInteraction,
  GrpcRequest,
  GrpcResponse,
  HeaderMap,
  HttpInteraction,
  HttpRequest,
  HttpResponse,
  MatchConfig,
  Matcher,
  SecurityConfig,
  WsFrame,
  WsInteraction,
} from "./types.js";

export { FetchInterceptor } from "./intercept/fetch.js";
export { isLocalhost } from "./intercept/base.js";
export type { Interceptor } from "./intercept/base.js";

// Primitives from the shared Rust core.
export {
  processBody,
  scrubGrpcInteraction,
  scrubInteraction,
  scrubWsInteraction,
  defaultBodyScrubPatterns,
  defaultFilterHeaders,
  defaultFilterQueryParameters,
  defaultMatchOn,
  defaultReplacement,
  formatVersion,
  knownMatchers,
} from "./binding.js";
