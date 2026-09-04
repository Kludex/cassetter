from __future__ import annotations

import json
from pathlib import Path

import pytest
from typing_extensions import NotRequired, TypedDict

from cassetter._core import (
    Cassette,
    SecurityConfig,
    scrub_grpc_interaction,
    scrub_interaction,
    scrub_ws_interaction,
)
from tests.conformance_helpers import canonical_cassette

FIXTURES = Path(__file__).parent.parent / "conformance" / "filtering"


class FilteringCase(TypedDict):
    name: str
    filterHeaders: NotRequired[list[str]]
    filterQueryParameters: NotRequired[list[str]]
    bodyScrubPatterns: NotRequired[list[str]]
    replacement: NotRequired[str]
    expected: str


CASES: list[FilteringCase] = json.loads((FIXTURES / "cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_filtering_cases(case: FilteringCase) -> None:
    cassette = Cassette.load(str(FIXTURES / "input.yaml"))
    config = SecurityConfig(
        filter_headers=case.get("filterHeaders"),
        filter_query_parameters=case.get("filterQueryParameters"),
        body_scrub_patterns=case.get("bodyScrubPatterns"),
        replacement=case.get("replacement"),
    )
    cassette.interactions = [scrub_interaction(interaction, config) for interaction in cassette.interactions]
    cassette.grpc_interactions = [
        scrub_grpc_interaction(interaction, config) for interaction in cassette.grpc_interactions
    ]
    cassette.ws_interactions = [scrub_ws_interaction(interaction, config) for interaction in cassette.ws_interactions]

    expected = json.loads((FIXTURES / case["expected"]).read_text())
    assert canonical_cassette(cassette) == expected
