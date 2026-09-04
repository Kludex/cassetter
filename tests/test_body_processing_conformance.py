from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from typing_extensions import NotRequired, TypedDict

from cassetter._core import process_body
from tests.conformance_helpers import canonical_body

FIXTURES = Path(__file__).parent.parent / "conformance" / "body-processing"


class RawBody(TypedDict):
    type: str
    content: NotRequired[str]


class RawMessage(TypedDict):
    headers: NotRequired[dict[str, list[str]]]
    body: RawBody


class RawRequest(TypedDict):
    uri: str


class RawInteraction(TypedDict):
    request: RawRequest
    response: RawMessage


class RawCassette(TypedDict):
    interactions: list[RawInteraction]


def body_bytes(body: RawBody) -> bytes:
    if body["type"] == "binary":
        return bytes.fromhex(body["content"])
    if body["type"] == "text":
        return body["content"].encode()
    return b""


def header(headers: dict[str, list[str]], name: str) -> str | None:
    for key, values in headers.items():
        if key.lower() == name and values:
            return values[0]
    return None


def test_shared_body_processing_cases() -> None:
    source: RawCassette = yaml.safe_load((FIXTURES / "cases.yaml").read_text(encoding="utf-8"))
    expected: dict[str, dict[str, Any]] = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))

    actual: dict[str, dict[str, Any]] = {}
    for interaction in source["interactions"]:
        response = interaction["response"]
        headers = response.get("headers", {})
        actual[interaction["request"]["uri"]] = canonical_body(
            process_body(
                body_bytes(response["body"]),
                header(headers, "content-type"),
                header(headers, "content-encoding"),
            )
        )

    assert actual == expected
