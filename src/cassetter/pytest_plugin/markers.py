from __future__ import annotations

import pytest

from cassetter.pytest_plugin.orphans import loaded_cassettes


def configure(config: pytest.Config) -> None:
    """Register the @pytest.mark.vcr marker and initialize cassette tracking."""
    config.addinivalue_line(
        "markers",
        "vcr(cassette_name, **kwargs): Mark test to use VCR cassette recording/replay.",
    )
    config.addinivalue_line(
        "markers",
        "default_cassette(cassette_name): Name the cassette, as pytest-recording spells it.",
    )
    loaded_cassettes(config)
