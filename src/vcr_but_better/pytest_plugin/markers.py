from __future__ import annotations

from typing import Any


def configure(config: Any) -> None:
    """Register the @pytest.mark.vcr marker."""
    config.addinivalue_line(
        "markers",
        "vcr(cassette_name, **kwargs): Mark test to use VCR cassette recording/replay.",
    )

    # Initialize cassette tracking set
    try:
        config.option
    except AttributeError:
        return

    config._vcr_loaded_cassettes = set()  # type: ignore[attr-defined]
