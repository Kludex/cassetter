from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from typing_extensions import NotRequired, TypedDict

from cassetter._core import Body, Cassette, HttpRequest, MatchConfig

FIXTURES = Path(__file__).parent.parent / "conformance" / "matching"

BodyKind = Literal["json", "text", "binary", "none"]
MatcherKind = Literal["method", "uri", "headers", "body", "json_body"]


class BodyValue(TypedDict):
    type: BodyKind
    content: NotRequired[Any]


class RequestValue(TypedDict):
    method: str
    uri: str
    headers: NotRequired[dict[str, list[str]]]
    body: NotRequired[BodyValue]


class MatchingCase(TypedDict):
    name: str
    matchOn: NotRequired[list[MatcherKind]]
    ignoreJsonPaths: NotRequired[list[str]]
    requests: list[RequestValue]
    expectedStatuses: list[int | None]


CASES: list[MatchingCase] = json.loads((FIXTURES / "cases.json").read_text())


def request_from_value(value: RequestValue) -> HttpRequest:
    if "body" in value:
        body_value = value["body"]
        body = Body(body_value["type"], body_value.get("content"))
    else:
        body = Body("none")
    return HttpRequest(value["method"], value["uri"], value.get("headers"), body)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_matching_cases(case: MatchingCase) -> None:
    cassette = Cassette.load(str(FIXTURES / "cassette.yaml"))
    config = MatchConfig(
        match_on=case.get("matchOn"),
        ignore_json_paths=case.get("ignoreJsonPaths"),
    )

    statuses: list[int | None] = []
    for value in case["requests"]:
        match = cassette.take_match(request_from_value(value), config)
        statuses.append(None if match is None else match[1].response.status)

    assert statuses == case["expectedStatuses"]
