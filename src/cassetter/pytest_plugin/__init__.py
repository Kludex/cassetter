from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from cassetter.pytest_plugin import unplayed
from cassetter.pytest_plugin.fixtures import (
    cassette as cassette,
    vcr as vcr,
    vcr_cassette_dir as vcr_cassette_dir,
    vcr_config as vcr_config,
)
from cassetter.pytest_plugin.markers import configure as configure
from cassetter.pytest_plugin.orphans import (
    OrphanedCassetteWarning as OrphanedCassetteWarning,
    WorkerNode,
    add_options,
    check_orphans as check_orphans,
    node_down,
    session_finish,
)
from cassetter.pytest_plugin.unplayed import UnplayedInteractionsWarning as UnplayedInteractionsWarning

__all__ = [
    "OrphanedCassetteWarning",
    "UnplayedInteractionsWarning",
    "cassette",
    "check_orphans",
    "configure",
    "vcr",
    "vcr_cassette_dir",
    "vcr_config",
]


class _XdistOrphanAggregator:
    """Collects each worker's loaded cassettes as it shuts down.

    Registered only when xdist is present: `pytest_testnodedown` is an xdist
    hook, and declaring it unconditionally makes pluggy reject the plugin for
    everyone who does not have xdist installed.
    """

    def pytest_testnodedown(self, node: WorkerNode, error: object) -> None:
        node_down(node)


def pytest_configure(config: pytest.Config) -> None:
    configure(config)
    if config.pluginmanager.hasplugin("xdist"):
        config.pluginmanager.register(_XdistOrphanAggregator(), "cassetter_xdist_orphans")


def pytest_addoption(parser: pytest.Parser) -> None:
    add_options(parser)
    unplayed.add_options(parser)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    unplayed.store_report(item, report)
    if report.when == "teardown":
        unplayed.check_after_teardown(item, report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    session_finish(session)
