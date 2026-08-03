from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from cassetter import Cassetter
from cassetter.cassette import Cassette

RECORDER = Cassetter(
    record_mode="none",
    cassette_library_dir=Path(__file__).parent / "cassettes" / "test_config_marker",
)


@pytest.fixture(scope="module")
def vcr_config() -> Cassetter:
    return RECORDER


@pytest.mark.vcr
def test_vcr_config_accepts_a_cassetter(cassette: Cassette) -> None:
    with httpx.Client() as client:
        response = client.get("https://example.com/config-test")
    assert response.status_code == 200
    assert response.json() == {"config": True}


def test_the_same_configuration_works_outside_pytest() -> None:
    with RECORDER.use_cassette("test_vcr_config_accepts_a_cassetter.yaml"):
        with httpx.Client() as client:
            response = client.get("https://example.com/config-test")
    assert response.json() == {"config": True}
