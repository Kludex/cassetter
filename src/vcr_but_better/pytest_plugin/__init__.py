from __future__ import annotations

from vcr_but_better.pytest_plugin.fixtures import vcr_cassette as vcr_cassette, vcr_config as vcr_config
from vcr_but_better.pytest_plugin.markers import configure as configure
from vcr_but_better.pytest_plugin.orphans import add_options, check_orphans as check_orphans, session_finish

__all__ = ["vcr_cassette", "vcr_config", "configure", "check_orphans"]


def pytest_configure(config: object) -> None:
    configure(config)


def pytest_addoption(parser: object) -> None:
    add_options(parser)


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    session_finish(session)
