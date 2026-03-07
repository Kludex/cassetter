from __future__ import annotations

from cassetter.pytest_plugin.fixtures import (
    cassette as cassette,
    vcr as vcr,
    vcr_cassette_dir as vcr_cassette_dir,
    vcr_config as vcr_config,
)
from cassetter.pytest_plugin.markers import configure as configure
from cassetter.pytest_plugin.orphans import add_options, check_orphans as check_orphans, session_finish

__all__ = ["cassette", "vcr", "vcr_cassette_dir", "vcr_config", "configure", "check_orphans"]


def pytest_configure(config: object) -> None:
    configure(config)


def pytest_addoption(parser: object) -> None:
    add_options(parser)


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    session_finish(session)
