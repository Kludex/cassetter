from __future__ import annotations

from typing import Any


def configure(config: Any) -> None:
    """Register the @pytest.mark.vcr marker."""
    config.addinivalue_line(
        "markers",
        "vcr(cassette_name, **kwargs): Mark test to use VCR cassette recording/replay.",
    )

    # Add CLI options
    config.addinivalue_line("markers", "")

    # Record mode CLI option
    group = config.getini("markers")  # noqa: F841

    try:
        config.option
    except AttributeError:
        return

    # Initialize cassette tracking set
    config._vcr_loaded_cassettes = set()  # type: ignore[attr-defined]


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("vcr", "VCR cassette recording")
    group.addoption(
        "--record-mode",
        action="store",
        default=None,
        choices=["none", "new_episodes", "all", "once"],
        help="VCR record mode: none, new_episodes, all, once",
    )
