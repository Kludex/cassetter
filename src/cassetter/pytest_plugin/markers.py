from __future__ import annotations

import pytest

from cassetter.pytest_plugin.orphans import loaded_cassettes


def configure(config: pytest.Config) -> None:
    """Register the @pytest.mark.vcr marker and initialize cassette tracking."""
    config.addinivalue_line(
        "markers",
        "vcr(cassette_name, **kwargs): Mark test to use VCR cassette recording/replay.",
    )
    loaded_cassettes(config)
