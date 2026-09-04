from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from cassetter._core import Body, Cassette, process_body
from tests.conformance_helpers import canonical_body

FIXTURES = Path(__file__).parent.parent / "conformance" / "body-processing"


def body_bytes(body: Body) -> bytes:
    if body.body_type == "binary":
        return cast(bytes, body.content)
    return b""


def header(headers: dict[str, list[str]], name: str) -> str | None:
    for key, values in headers.items():
        if key.lower() == name and values:
            return values[0]
    return None


def test_shared_body_processing_cases() -> None:
    cassette = Cassette.load(str(FIXTURES / "cases.yaml"))
    expected: dict[str, dict[str, Any]] = json.loads((FIXTURES / "expected.json").read_text())

    actual = {
        interaction.request.uri: canonical_body(
            process_body(
                body_bytes(interaction.response.body),
                header(interaction.response.headers, "content-type"),
                header(interaction.response.headers, "content-encoding"),
            )
        )
        for interaction in cassette.interactions
    }

    assert actual == expected
