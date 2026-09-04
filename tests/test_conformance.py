"""Cross-language conformance.

Parses the shared fixture in ``conformance/`` and asserts it produces the
canonical structure every cassetter binding must agree on. The Node binding
runs the same assertions in ``ts/tests/conformance.test.ts``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cassetter._core import Body, Cassette

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "conformance" / "cassette.yaml"
EXPECTED = ROOT / "conformance" / "expected.json"


def _body(b: Body) -> dict[str, Any]:
    if b.body_type == "binary":
        return {"type": "binary", "content": b.content.hex()}
    if b.body_type == "none":
        return {"type": "none"}
    return {"type": b.body_type, "content": b.content}


def _headers(h: dict[str, list[str]]) -> dict[str, list[str]]:
    return {k: list(v) for k, v in sorted(h.items())}


def _canonical(c: Cassette) -> dict[str, Any]:
    return {
        "version": c.version,
        "http": [
            {
                "method": i.request.method,
                "uri": i.request.uri,
                "requestHeaders": _headers(i.request.headers),
                "requestBody": _body(i.request.body),
                "status": i.response.status,
                "responseHeaders": _headers(i.response.headers),
                "responseBody": _body(i.response.body),
                "recordedAt": i.recorded_at,
            }
            for i in c.interactions
        ],
        "grpc": [
            {
                "method": g.request.method,
                "metadata": _headers(g.request.metadata),
                "requestBody": _body(g.request.body),
                "statusCode": g.response.status_code,
                "statusMessage": g.response.status_message,
                "responseMetadata": _headers(g.response.metadata),
                "responseBody": _body(g.response.body),
                "jsonDebug": g.json_debug,
                "recordedAt": g.recorded_at,
            }
            for g in c.grpc_interactions
        ],
        "ws": [
            {
                "uri": w.uri,
                "headers": _headers(w.headers),
                "frames": [
                    {
                        "direction": f.direction,
                        "frameType": f.frame_type,
                        "body": _body(f.body),
                        "offsetMs": f.offset_ms,
                    }
                    for f in w.frames
                ],
                "recordedAt": w.recorded_at,
            }
            for w in c.ws_interactions
        ],
    }


def _expected() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return loaded


def test_fixture_matches_canonical_structure() -> None:
    assert _canonical(Cassette.load(str(FIXTURE))) == _expected()


def test_roundtrip_through_yaml_has_no_drift(tmp_path: Path) -> None:
    out = tmp_path / "roundtrip.yaml"
    Cassette.load(str(FIXTURE)).save(str(out))
    assert _canonical(Cassette.load(str(out))) == _expected()


def test_unicode_and_multi_value_headers_survive() -> None:
    c = Cassette.load(str(FIXTURE))
    assert c.interactions[1].request.body.content == "café — naïve ✓"
    assert c.interactions[0].request.headers["x-multi"] == ["one", "two"]
