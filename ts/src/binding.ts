/**
 * Loader and type surface for the native `cassetter-node` addon.
 *
 * Everything below is implemented in Rust by `cassetter-core` and shared with
 * the Python binding. Structured values cross the boundary shaped exactly like
 * the cassette file format.
 */

import { createRequire } from "node:module";

import type {
  Body,
  GrpcInteraction,
  HttpInteraction,
  HttpRequest,
  MatchConfig,
  SecurityConfig,
  WsInteraction,
} from "./types.js";

export interface MatchHit<T> {
  index: number;
  interaction: T;
}

export interface NativeCassette {
  readonly version: number;
  readonly length: number;

  save(path: string, order?: number[], mode?: number): void;
  toYaml(order?: number[]): string;
  toToml(order?: number[]): string;
  outputOrder(sortConfig?: MatchConfig, recordOrder?: number[]): number[];

  readonly interactions: HttpInteraction[];
  readonly playedIndices: boolean[];
  readonly unplayedCount: number;
  addInteraction(interaction: HttpInteraction): void;
  markPlayed(index: number): void;
  /** Match and mark played in one atomic step. */
  takeMatch(
    request: HttpRequest,
    config?: MatchConfig,
  ): MatchHit<HttpInteraction> | null;

  readonly grpcInteractions: GrpcInteraction[];
  readonly grpcPlayed: boolean[];
  addGrpcInteraction(interaction: GrpcInteraction): void;
  markGrpcPlayed(index: number): void;
  takeGrpcMatch(method: string): MatchHit<GrpcInteraction> | null;

  readonly wsInteractions: WsInteraction[];
  readonly wsPlayed: boolean[];
  addWsInteraction(interaction: WsInteraction): void;
  markWsPlayed(index: number): void;
  takeWsMatch(uri: string): MatchHit<WsInteraction> | null;
}

interface NativeBinding {
  Cassette: {
    new (): NativeCassette;
    load(path: string): NativeCassette;
    fromYaml(content: string): NativeCassette;
    fromToml(content: string): NativeCassette;
  };
  processBody(
    rawBytes: Buffer,
    contentType?: string | null,
    contentEncoding?: string | null,
    maxDecompressed?: number | null,
  ): Body;
  scrubInteraction(
    interaction: HttpInteraction,
    config?: SecurityConfig,
  ): HttpInteraction;
  scrubGrpcInteraction(
    interaction: GrpcInteraction,
    config?: SecurityConfig,
  ): GrpcInteraction;
  scrubWsInteraction(
    interaction: WsInteraction,
    config?: SecurityConfig,
  ): WsInteraction;
  defaultFilterHeaders(): string[];
  defaultFilterQueryParameters(): string[];
  defaultBodyScrubPatterns(): string[];
  defaultMatchOn(): string[];
  knownMatchers(): string[];
  defaultReplacement(): string;
  formatVersion(): number;
}

const require = createRequire(import.meta.url);

export const native: NativeBinding = require("../native/index.js") as NativeBinding;

export const {
  processBody,
  scrubInteraction,
  scrubGrpcInteraction,
  scrubWsInteraction,
  defaultFilterHeaders,
  defaultFilterQueryParameters,
  defaultBodyScrubPatterns,
  defaultMatchOn,
  knownMatchers,
  defaultReplacement,
  formatVersion,
} = native;
