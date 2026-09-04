import { gzipSync } from "node:zlib";

import { describe, expect, it } from "vitest";

import {
  defaultBodyScrubPatterns,
  defaultFilterHeaders,
  defaultFilterQueryParameters,
  defaultMatchOn,
  defaultReplacement,
  formatVersion,
  knownMatchers,
  processBody,
  scrubGrpcInteraction,
  scrubInteraction,
  scrubWsInteraction,
} from "../src/binding.js";
import { binaryBody, binaryBodyBytes, bodyToBuffer } from "../src/types.js";
import type { GrpcInteraction, HttpInteraction, WsInteraction } from "../src/types.js";

describe("defaults (sourced from the Rust core)", () => {
  it("exposes the shared security defaults", () => {
    const headers = defaultFilterHeaders();
    expect(headers).toContain("authorization");
    expect(headers).toContain("set-cookie");
    // Provider-specific credential headers are covered too.
    expect(headers).toContain("x-goog-api-key");
    expect(headers).toContain("x-amz-security-token");
    expect(defaultFilterQueryParameters()).toContain("api_key");
    expect(defaultBodyScrubPatterns()).toContain("password");
    expect(defaultReplacement()).toBe("[FILTERED]");
  });

  it("exposes the shared match defaults and format version", () => {
    expect(defaultMatchOn()).toEqual(["method", "uri"]);
    expect(knownMatchers()).toEqual([
      "method",
      "uri",
      "headers",
      "body",
      "json_body",
    ]);
    expect(formatVersion()).toBe(1);
  });
});

describe("processBody", () => {
  it("returns none for an empty body", () => {
    expect(processBody(Buffer.alloc(0))).toEqual({ type: "none" });
  });

  it("parses JSON when content-type says so", () => {
    const body = processBody(Buffer.from('{"key":"value"}'), "application/json");
    expect(body.type).toBe("json");
    expect(body.content).toEqual({ key: "value" });
  });

  it("honours charset and +json suffixes", () => {
    expect(
      processBody(Buffer.from("{}"), "application/json; charset=utf-8").type,
    ).toBe("json");
    expect(processBody(Buffer.from("{}"), "application/vnd.api+json").type).toBe(
      "json",
    );
  });

  it("sniffs JSON when no content-type is given", () => {
    // The core parses JSON opportunistically when the type is unknown.
    const body = processBody(Buffer.from('{"a":1}'));
    expect(body.type).toBe("json");
    expect(body.content).toEqual({ a: 1 });
  });

  it("preserves JSON key order as the server sent it", () => {
    const body = processBody(
      Buffer.from('{"zebra":1,"apple":2,"mango":3}'),
      "application/json",
    );
    expect(Object.keys(body.content as object)).toEqual([
      "zebra",
      "apple",
      "mango",
    ]);
  });

  it("returns text for non-JSON content", () => {
    const body = processBody(Buffer.from("hello world"), "text/plain");
    expect(body.type).toBe("text");
    expect(body.content).toBe("hello world");
  });

  it("falls back to text when the content-type lies", () => {
    const body = processBody(Buffer.from("not json"), "application/json");
    expect(body.type).toBe("text");
    expect(body.content).toBe("not json");
  });

  it("returns binary (hex) for non-UTF-8 bytes", () => {
    const body = processBody(Buffer.from([0xff, 0xfe, 0x00, 0x01]));
    expect(body.type).toBe("binary");
    expect(binaryBodyBytes(body)).toEqual(Buffer.from([0xff, 0xfe, 0x00, 0x01]));
  });

  it("decompresses gzip", () => {
    const body = processBody(
      gzipSync(Buffer.from('{"z":true}')),
      "application/json",
      "gzip",
    );
    expect(body.type).toBe("json");
    expect(body.content).toEqual({ z: true });
  });

  it("rejects a body that decompresses past the cap", () => {
    expect(() =>
      processBody(gzipSync(Buffer.alloc(4096, 97)), "text/plain", "gzip", 16),
    ).toThrow();
  });

  it("NFC-normalizes text", () => {
    const body = processBody(Buffer.from("é"), "text/plain");
    expect(body.content).toBe("é");
  });
});

describe("scrubInteraction", () => {
  const interaction: HttpInteraction = {
    request: {
      method: "POST",
      uri: "https://api.example.com/login?api_key=s3cret&keep=yes",
      headers: {
        authorization: ["Bearer token"],
        "content-type": ["application/json"],
      },
      body: { type: "json", content: { user: "kate", password: "hunter2" } },
    },
    response: {
      status: 200,
      headers: { "set-cookie": ["session=abc"], "x-ok": ["1"] },
      body: { type: "json", content: { access_token: "tok", ok: true } },
    },
    recordedAt: "2026-01-01T00:00:00Z",
  };

  it("applies the default filters", () => {
    const out = scrubInteraction(interaction, {});

    expect(out.request.headers.authorization).toBeUndefined();
    expect(out.request.headers["content-type"]).toEqual(["application/json"]);
    expect(out.response.headers["set-cookie"]).toBeUndefined();
    expect(out.response.headers["x-ok"]).toEqual(["1"]);

    expect(out.request.uri).not.toContain("s3cret");
    expect(out.request.uri).toContain("keep=yes");

    const reqBody = out.request.body.content as Record<string, unknown>;
    const respBody = out.response.body.content as Record<string, unknown>;
    expect(reqBody.password).toBe("[FILTERED]");
    expect(reqBody.user).toBe("kate");
    expect(respBody.access_token).toBe("[FILTERED]");
    expect(respBody.ok).toBe(true);
  });

  it("adds custom filters to the defaults rather than replacing them", () => {
    const out = scrubInteraction(interaction, {
      filterHeaders: ["x-ok"],
      bodyScrubPatterns: ["user"],
      replacement: "***",
    });

    // The custom entry is scrubbed...
    expect(out.response.headers["x-ok"]).toBeUndefined();
    expect((out.request.body.content as Record<string, unknown>).user).toBe("***");
    // ...and the built-ins still are, which is the whole point.
    expect(out.request.headers.authorization).toBeUndefined();
    expect((out.request.body.content as Record<string, unknown>).password).toBe(
      "***",
    );
  });
});

describe("scrubGrpcInteraction", () => {
  it("scrubs metadata and jsonDebug but leaves binary bodies alone", () => {
    const interaction: GrpcInteraction = {
      request: {
        method: "/demo.Svc/M",
        metadata: { authorization: ["Bearer x"], "x-trace": ["abc"] },
        body: binaryBody(Buffer.from([1, 2, 3])),
      },
      response: {
        statusCode: 0,
        statusMessage: "OK",
        metadata: { "set-cookie": ["s=1"] },
        body: binaryBody(Buffer.from([4, 5])),
      },
      recordedAt: "2026-01-01T00:00:00Z",
      jsonDebug: { request: { password: "hunter2", user: "kate" } },
    };

    const out = scrubGrpcInteraction(interaction, {});

    expect(out.request.metadata.authorization).toBeUndefined();
    expect(out.request.metadata["x-trace"]).toEqual(["abc"]);
    expect(out.response.metadata["set-cookie"]).toBeUndefined();
    const debug = out.jsonDebug as { request: Record<string, unknown> };
    expect(debug.request.password).toBe("[FILTERED]");
    expect(debug.request.user).toBe("kate");
    // Binary protobuf bodies cannot be pattern-scrubbed, so they pass through.
    expect(out.request.body).toEqual(interaction.request.body);
  });
});

describe("scrubWsInteraction", () => {
  it("scrubs handshake headers and text/JSON frame bodies", () => {
    const interaction: WsInteraction = {
      uri: "wss://api.example.com/v1",
      headers: { authorization: ["Bearer x"], origin: ["https://example.com"] },
      frames: [
        {
          direction: "send",
          frameType: "text",
          body: { type: "json", content: { access_token: "tok", channel: "t" } },
          offsetMs: 0,
        },
        {
          direction: "recv",
          frameType: "binary",
          body: binaryBody(Buffer.from([1, 2, 3])),
          offsetMs: 10,
        },
      ],
      recordedAt: "2026-01-01T00:00:00Z",
    };

    const out = scrubWsInteraction(interaction, {});

    expect(out.headers.authorization).toBeUndefined();
    expect(out.headers.origin).toEqual(["https://example.com"]);
    const frame = out.frames[0].body.content as Record<string, unknown>;
    expect(frame.access_token).toBe("[FILTERED]");
    expect(frame.channel).toBe("t");
    expect(out.frames[1].body).toEqual(interaction.frames[1].body);
  });
});

describe("body helpers", () => {
  it("round-trips binary through hex", () => {
    const buf = Buffer.from([0x00, 0x7f, 0xff]);
    const body = binaryBody(buf);
    expect(body).toEqual({ type: "binary", content: "007fff" });
    expect(binaryBodyBytes(body)).toEqual(buf);
  });

  it("converts every body type to bytes", () => {
    expect(bodyToBuffer({ type: "none" })).toEqual(Buffer.alloc(0));
    expect(bodyToBuffer({ type: "text", content: "hi" }).toString()).toBe("hi");
    expect(bodyToBuffer({ type: "json", content: { a: 1 } }).toString()).toBe(
      '{"a":1}',
    );
    expect(bodyToBuffer(binaryBody(Buffer.from("xy"))).toString()).toBe("xy");
  });

  it("rejects reading a non-binary body as bytes", () => {
    expect(() => binaryBodyBytes({ type: "text", content: "x" })).toThrow(
      /expected a binary body/,
    );
  });
});
