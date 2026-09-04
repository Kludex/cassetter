"""Cross-language cassette-format conformance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import TypedDict

from cassetter._core import Body, Cassette

ROOT = Path(__file__).parent.parent
FORMAT_FIXTURES = ROOT / "conformance" / "format"


class FormatCase(TypedDict):
    name: str
    cassette: str
    expected: str


class InvalidFormatCase(TypedDict):
    name: str
    cassette: str


FORMAT_CASES: list[FormatCase] = json.loads((FORMAT_FIXTURES / "cases.json").read_text(encoding="utf-8"))
INVALID_FORMAT_CASES: list[InvalidFormatCase] = json.loads(
    (FORMAT_FIXTURES / "invalid" / "cases.json").read_text(encoding="utf-8")
)


def _body(body: Body) -> dict[str, Any]:
    if body.body_type == "binary":
        return {"type": "binary", "content": body.content.hex()}
    if body.body_type == "none":
        return {"type": "none"}
    return {"type": body.body_type, "content": body.content}


def _headers(headers: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: list(value) for key, value in sorted(headers.items())}


def _canonical(cassette: Cassette) -> dict[str, Any]:
    return {
        "version": cassette.version,
        "http": [
            {
                "method": interaction.request.method,
                "uri": interaction.request.uri,
                "requestHeaders": _headers(interaction.request.headers),
                "requestBody": _body(interaction.request.body),
                "status": interaction.response.status,
                "responseHeaders": _headers(interaction.response.headers),
                "responseBody": _body(interaction.response.body),
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.interactions
        ],
        "grpc": [
            {
                "method": interaction.request.method,
                "metadata": _headers(interaction.request.metadata),
                "requestBody": _body(interaction.request.body),
                "statusCode": interaction.response.status_code,
                "statusMessage": interaction.response.status_message,
                "responseMetadata": _headers(interaction.response.metadata),
                "responseBody": _body(interaction.response.body),
                "jsonDebug": interaction.json_debug,
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.grpc_interactions
        ],
        "ws": [
            {
                "uri": interaction.uri,
                "headers": _headers(interaction.headers),
                "frames": [
                    {
                        "direction": frame.direction,
                        "frameType": frame.frame_type,
                        "body": _body(frame.body),
                        "offsetMs": frame.offset_ms,
                    }
                    for frame in interaction.frames
                ],
                "recordedAt": interaction.recorded_at,
            }
            for interaction in cassette.ws_interactions
        ],
    }


@pytest.mark.parametrize("case", FORMAT_CASES, ids=[case["name"] for case in FORMAT_CASES])
def test_fixture_matches_canonical_structure(case: FormatCase) -> None:
    cassette = Cassette.load(str(FORMAT_FIXTURES / case["cassette"]))
    expected = json.loads((FORMAT_FIXTURES / case["expected"]).read_text(encoding="utf-8"))
    assert _canonical(cassette) == expected


@pytest.mark.parametrize("case", FORMAT_CASES, ids=[case["name"] for case in FORMAT_CASES])
def test_roundtrip_through_storage_format_has_no_drift(tmp_path: Path, case: FormatCase) -> None:
    output = tmp_path / case["cassette"]
    Cassette.load(str(FORMAT_FIXTURES / case["cassette"])).save(str(output))
    expected = json.loads((FORMAT_FIXTURES / case["expected"]).read_text(encoding="utf-8"))
    assert _canonical(Cassette.load(str(output))) == expected


@pytest.mark.parametrize(
    "case",
    INVALID_FORMAT_CASES,
    ids=[case["name"] for case in INVALID_FORMAT_CASES],
)
def test_invalid_fixture_is_rejected(case: InvalidFormatCase) -> None:
    with pytest.raises(ValueError):
        Cassette.load(str(FORMAT_FIXTURES / "invalid" / case["cassette"]))


def test_unicode_and_multi_value_headers_survive() -> None:
    cassette = Cassette.load(str(FORMAT_FIXTURES / "all-protocols.yaml"))
    assert cassette.interactions[1].request.body.content == "café — naïve ✓"
    assert cassette.interactions[0].request.headers["x-multi"] == ["one", "two"]
