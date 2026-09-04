import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type {
  Body,
  GrpcInteraction,
  HeaderMap,
  HttpInteraction,
  WsInteraction,
} from "../src/types.js";

export const CONFORMANCE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function sortKeys<T extends object>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).sort(([left], [right]) => (left < right ? -1 : 1)),
  ) as T;
}

export function canonicalBody(value: Body): object {
  return value.type === "none"
    ? { type: "none" }
    : { type: value.type, content: value.content };
}

function headers(value: HeaderMap): HeaderMap {
  return sortKeys(value);
}

export function canonicalCassette(cassette: {
  version: number;
  interactions: HttpInteraction[];
  grpcInteractions: GrpcInteraction[];
  wsInteractions: WsInteraction[];
}): object {
  return {
    version: cassette.version,
    http: cassette.interactions.map((interaction) => ({
      method: interaction.request.method,
      uri: interaction.request.uri,
      requestHeaders: headers(interaction.request.headers),
      requestBody: canonicalBody(interaction.request.body),
      status: interaction.response.status,
      responseHeaders: headers(interaction.response.headers),
      responseBody: canonicalBody(interaction.response.body),
      recordedAt: interaction.recordedAt,
    })),
    grpc: cassette.grpcInteractions.map((interaction) => ({
      method: interaction.request.method,
      metadata: headers(interaction.request.metadata),
      requestBody: canonicalBody(interaction.request.body),
      statusCode: interaction.response.statusCode,
      statusMessage: interaction.response.statusMessage,
      responseMetadata: headers(interaction.response.metadata),
      responseBody: canonicalBody(interaction.response.body),
      jsonDebug: interaction.jsonDebug ?? null,
      recordedAt: interaction.recordedAt,
    })),
    ws: cassette.wsInteractions.map((interaction) => ({
      uri: interaction.uri,
      headers: headers(interaction.headers),
      frames: interaction.frames.map((frame) => ({
        direction: frame.direction,
        frameType: frame.frameType,
        body: canonicalBody(frame.body),
        offsetMs: frame.offsetMs,
      })),
      recordedAt: interaction.recordedAt,
    })),
  };
}
