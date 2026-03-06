#!/usr/bin/env python3
"""Convert vcrpy cassette YAML files to cassetter format.

Usage:
    python scripts/convert_vcrpy.py <directory>

Recursively finds all .yaml files in the directory and converts them
from vcrpy format to cassetter format in-place.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cassetter._core import (
    Body,
    Cassette,
    GrpcInteraction,
    GrpcRequest,
    GrpcResponse,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
)


def _convert_body(raw: object, parsed: object) -> Body:
    """Convert a vcrpy body (raw + parsed_body) to a cassetter Body."""
    # parsed_body takes priority - it's the structured JSON
    if parsed is not None:
        return Body("json", parsed)

    # body: {string: "..."} format (vcrpy response body)
    if isinstance(raw, dict) and "string" in raw:
        text = raw["string"]
        if text is None or text == "":
            return Body("none")
        if isinstance(text, bytes):
            return Body("binary", text)
        # Try to parse as JSON
        if isinstance(text, str):
            try:
                return Body("json", json.loads(text))
            except (json.JSONDecodeError, ValueError):
                pass
        return Body("text", str(text))

    if raw is None:
        return Body("none")

    if isinstance(raw, bytes):
        return Body("binary", raw)

    if isinstance(raw, str):
        if raw == "":
            return Body("none")
        # Try to parse as JSON string
        try:
            return Body("json", json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return Body("text", raw)

    # Fallback - shouldn't happen
    return Body("text", str(raw))


def _convert_headers(headers: dict[str, list[object]] | None) -> dict[str, list[str]]:
    """Convert headers, decoding any binary values."""
    if not headers:
        return {}
    result: dict[str, list[str]] = {}
    for key, values in headers.items():
        str_values: list[str] = []
        for v in values:
            if isinstance(v, bytes):
                str_values.append(v.decode("utf-8", errors="replace"))
            else:
                str_values.append(str(v))
        result[key] = str_values
    return result


def _convert_status(status: object) -> int:
    """Convert vcrpy status {code: int, message: str} to just the int."""
    if isinstance(status, dict):
        return int(status.get("code", 0))
    if isinstance(status, int):
        return status
    return 0


def convert_file(path: Path) -> bool:
    """Convert a single vcrpy cassette file to cassetter format. Returns True if converted."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return False

    # Skip files that are already in cassetter format (have body.type structure)
    interactions = data.get("interactions", [])
    if not interactions:
        # Might be a gRPC-only cassette already in cassetter format
        if "grpc_interactions" in data and "interactions" not in data:
            return False
        if not interactions:
            return False

    # Detect if already in cassetter format by checking first interaction
    first = interactions[0]
    req = first.get("request", {})
    if isinstance(req.get("body"), dict) and "type" in req.get("body", {}):
        return False  # Already cassetter format

    # Also skip if this has grpc_interactions (mixed cassettes managed by xai_proto_cassettes.py)
    if "grpc_interactions" in data:
        return False

    now = datetime.now(timezone.utc).isoformat()
    cassette = Cassette()

    for interaction in interactions:
        req_data = interaction.get("request", {})
        resp_data = interaction.get("response", {})

        # Request
        method = req_data.get("method", "GET")
        uri = req_data.get("uri", "")
        req_headers = _convert_headers(req_data.get("headers"))
        req_body = _convert_body(req_data.get("body"), req_data.get("parsed_body"))

        # Response
        status = _convert_status(resp_data.get("status", 0))
        resp_headers = _convert_headers(resp_data.get("headers"))
        resp_body = _convert_body(resp_data.get("body"), resp_data.get("parsed_body"))

        recorded_at = interaction.get("recorded_at", now)

        cassette.add_interaction(
            HttpInteraction(
                request=HttpRequest(method, uri, req_headers, req_body),
                response=HttpResponse(status, resp_headers, resp_body),
                recorded_at=recorded_at,
            )
        )

    # Handle grpc_interactions if present alongside http interactions
    for grpc_interaction in data.get("grpc_interactions", []):
        req_data = grpc_interaction.get("request", {})
        resp_data = grpc_interaction.get("response", {})

        method = req_data.get("method", "")
        metadata = _convert_headers(req_data.get("metadata"))
        req_body = _convert_body(req_data.get("body"), None)

        status_code = resp_data.get("status_code", 0)
        status_message = resp_data.get("status_message", "OK")
        resp_metadata = _convert_headers(resp_data.get("metadata"))
        resp_body = _convert_body(resp_data.get("body"), None)

        recorded_at = grpc_interaction.get("recorded_at", now)
        json_debug = grpc_interaction.get("json_debug")

        cassette.add_grpc_interaction(
            GrpcInteraction(
                request=GrpcRequest(method, metadata, req_body),
                response=GrpcResponse(status_code, status_message, resp_metadata, resp_body),
                recorded_at=recorded_at,
                json_debug=json_debug,
            )
        )

    cassette.save(str(path))
    return True


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>", file=sys.stderr)
        sys.exit(1)

    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    converted = 0
    skipped = 0
    errors = 0

    for path in sorted(root.rglob("*.yaml")):
        try:
            if convert_file(path):
                converted += 1
                print(f"  converted: {path}")
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR: {path}: {e}", file=sys.stderr)

    print(f"\nDone: {converted} converted, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    main()
