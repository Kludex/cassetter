from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typing_extensions import TypedDict

from cassetter._core import Cassette as CoreCassette
from cassetter.cassette import Cassette, NoMatchError
from cassetter.recording import RecordMode

FIXTURES = Path(__file__).parent.parent / "conformance" / "record-modes"


class StoredInteraction(TypedDict):
    uri: str
    status: int


class RecordModeCase(TypedDict):
    name: str
    mode: str
    existing: bool
    requests: list[str]
    expectedOutcomes: list[str]
    expectedBaseCalls: int
    expectedFile: list[StoredInteraction] | None


CASES: list[RecordModeCase] = json.loads((FIXTURES / "cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_record_mode_cases(tmp_path: Path, case: RecordModeCase) -> None:
    path = tmp_path / "cassette.yaml"
    if case["existing"]:
        shutil.copyfile(FIXTURES / "existing.yaml", path)

    cassette = Cassette(path, record_mode=RecordMode.from_str(case["mode"]))
    cassette.load()
    outcomes: list[str] = []
    base_calls = 0
    for uri in case["requests"]:
        try:
            cassette.play("GET", uri, {}, None)
        except NoMatchError:
            if not cassette.can_record:
                outcomes.append("no_match")
                continue
            cassette.record(
                "GET",
                uri,
                {},
                None,
                299,
                {"content-type": ["application/json"]},
                b'{"source":"live"}',
            )
            outcomes.append("live")
            base_calls += 1
        else:
            outcomes.append("replay")
    cassette.save()

    assert outcomes == case["expectedOutcomes"]
    assert base_calls == case["expectedBaseCalls"]
    if case["expectedFile"] is None:
        assert not path.exists()
    else:
        stored = CoreCassette.load(str(path))
        actual: list[StoredInteraction] = [
            {"uri": interaction.request.uri, "status": interaction.response.status}
            for interaction in stored.interactions
        ]
        actual.sort(key=lambda interaction: interaction["uri"])
        assert actual == case["expectedFile"]
