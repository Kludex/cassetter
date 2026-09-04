from __future__ import annotations

from typing import Any

from cassetter._core import Body, Cassette


def canonical_body(body: Body) -> dict[str, Any]:
    if body.body_type == "binary":
        return {"type": "binary", "content": body.content.hex()}
    if body.body_type == "none":
        return {"type": "none"}
    return {"type": body.body_type, "content": body.content}


def canonical_headers(headers: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: list(value) for key, value in sorted(headers.items())}


def canonical_cassette(cassette: Cassette) -> dict[str, Any]:
    return {
        "version": cassette.version,
        "http": [
            {
                "method": interaction.request.method,
                "uri": interaction.request.uri,
                "requestHeaders": canonical_headers(interaction.request.headers),
                "requestBody": canonical_body(interaction.request.body),
                "status": interaction.response.status,
                "responseHeaders": canonical_headers(interaction.response.headers),
                "responseBody": canonical_body(interaction.response.body),
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.interactions
        ],
        "grpc": [
            {
                "method": interaction.request.method,
                "metadata": canonical_headers(interaction.request.metadata),
                "requestBody": canonical_body(interaction.request.body),
                "statusCode": interaction.response.status_code,
                "statusMessage": interaction.response.status_message,
                "responseMetadata": canonical_headers(interaction.response.metadata),
                "responseBody": canonical_body(interaction.response.body),
                "jsonDebug": interaction.json_debug,
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.grpc_interactions
        ],
        "ws": [
            {
                "uri": interaction.uri,
                "headers": canonical_headers(interaction.headers),
                "frames": [
                    {
                        "direction": frame.direction,
                        "frameType": frame.frame_type,
                        "body": canonical_body(frame.body),
                        "offsetMs": frame.offset_ms,
                    }
                    for frame in interaction.frames
                ],
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.ws_interactions
        ],
    }
