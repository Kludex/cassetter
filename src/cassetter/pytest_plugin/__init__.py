from __future__ import annotations

import pytest

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

__all__ = [
    "OrphanedCassetteWarning",
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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    session_finish(session)
