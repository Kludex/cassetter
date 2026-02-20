from __future__ import annotations

import httpx
import pytest

from cassetter._types import CassetteConfig
from cassetter.cassette import Cassette


@pytest.fixture(scope="module")
def vcr_config() -> CassetteConfig:
    return CassetteConfig(record_mode="none", cassette_dir="cassettes")


@pytest.mark.vcr
def test_with_marker(vcr_cassette: Cassette) -> None:
    with httpx.Client() as client:
        response = client.get("https://example.com/marker-test")
    assert response.status_code == 200
    assert response.json() == {"marker": True}
