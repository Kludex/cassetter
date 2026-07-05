from __future__ import annotations

import os
import warnings
from typing import Any


def add_options(parser: Any) -> None:
    """Add --vcr-check-orphans CLI option."""
    group = parser.getgroup("vcr", "VCR cassette recording")
    group.addoption(
        "--record-mode",
        action="store",
        default=None,
        choices=["none", "new_episodes", "all", "once"],
        help="VCR record mode: none, new_episodes, all, once",
    )
    group.addoption(
        "--vcr-check-orphans",
        action="store",
        default=None,
        metavar="DIR",
        help="Check for orphaned cassette files in DIR that were not loaded during the test run.",
    )


def session_finish(session: Any) -> None:
    """Check for orphaned cassettes at the end of the test session."""
    config = session.config
    orphan_dir = config.getoption("--vcr-check-orphans", default=None)
    if orphan_dir is None:
        return

    loaded: set[str] = getattr(config, "_vcr_loaded_cassettes", set())
    orphan_dir = os.path.abspath(orphan_dir)

    orphans: list[str] = []
    for root, _dirs, files in os.walk(orphan_dir):
        for f in files:
            if f.endswith((".yaml", ".yml", ".toml")):
                full_path = os.path.abspath(os.path.join(root, f))
                if full_path not in loaded:
                    orphans.append(os.path.relpath(full_path, orphan_dir))

    if orphans:
        orphan_list = "\n  ".join(sorted(orphans))
        warnings.warn(
            f"Found {len(orphans)} orphaned cassette file(s) in {orphan_dir}:\n  {orphan_list}",
            stacklevel=1,
        )


def check_orphans(cassette_dir: str, loaded_paths: set[str]) -> list[str]:
    """Return list of cassette files in cassette_dir not in loaded_paths."""
    orphans = []
    cassette_dir = os.path.abspath(cassette_dir)
    for root, _dirs, files in os.walk(cassette_dir):
        for f in files:
            if f.endswith((".yaml", ".yml", ".toml")):
                full_path = os.path.abspath(os.path.join(root, f))
                if full_path not in loaded_paths:
                    orphans.append(os.path.relpath(full_path, cassette_dir))
    return sorted(orphans)
