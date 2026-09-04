"""Cross-language cassette-format conformance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typing_extensions import TypedDict

from cassetter._core import Cassette
from tests.conformance_helpers import canonical_cassette

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


@pytest.mark.parametrize("case", FORMAT_CASES, ids=[case["name"] for case in FORMAT_CASES])
def test_fixture_matches_canonical_structure(case: FormatCase) -> None:
    cassette = Cassette.load(str(FORMAT_FIXTURES / case["cassette"]))
    expected = json.loads((FORMAT_FIXTURES / case["expected"]).read_text(encoding="utf-8"))
    assert canonical_cassette(cassette) == expected


@pytest.mark.parametrize("case", FORMAT_CASES, ids=[case["name"] for case in FORMAT_CASES])
def test_roundtrip_through_storage_format_has_no_drift(tmp_path: Path, case: FormatCase) -> None:
    output = tmp_path / case["cassette"]
    Cassette.load(str(FORMAT_FIXTURES / case["cassette"])).save(str(output))
    expected = json.loads((FORMAT_FIXTURES / case["expected"]).read_text(encoding="utf-8"))
    assert canonical_cassette(Cassette.load(str(output))) == expected


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
