from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from typing import Protocol, TypedDict, cast

import pytest

#: Cassette paths loaded during this session, stashed on the pytest config.
LOADED_CASSETTES: pytest.StashKey[set[str]] = pytest.StashKey()


class OrphanedCassetteWarning(UserWarning):
    """Emitted when a cassette file on disk was not loaded during the test run."""


class WorkerOutput(TypedDict, total=False):
    """The slice of an xdist worker's output payload that this plugin owns."""

    vcr_loaded_cassettes: list[str]


class XdistWorkerConfig(Protocol):
    """A pytest config running inside an xdist worker."""

    workerinput: Mapping[str, object]
    workeroutput: WorkerOutput


class WorkerNode(Protocol):
    """The slice of xdist's `WorkerController` that orphan aggregation reads."""

    config: pytest.Config
    workeroutput: WorkerOutput


def add_options(parser: pytest.Parser) -> None:
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
    parser.addini("vcr_max_age", "Default cassette max age (e.g. '30d'), overridable per test.", default=None)
    parser.addini(
        "vcr_on_expiry",
        "Action for expired cassettes: warn, fail, or rerecord.",
        default=None,
    )


def loaded_cassettes(config: pytest.Config) -> set[str]:
    """The set of cassette paths loaded in this process."""
    return config.stash.setdefault(LOADED_CASSETTES, set())


def is_xdist_worker(config: pytest.Config) -> bool:
    """Whether this process is a pytest-xdist worker rather than the controller."""
    return hasattr(config, "workerinput")


def node_down(node: WorkerNode) -> None:
    """Merge a finished xdist worker's loaded cassettes into the controller's set.

    Each worker only sees the tests in its own shard, so without this the
    controller reports every cassette the other workers used as an orphan.
    """
    loaded = node.workeroutput.get("vcr_loaded_cassettes")
    if loaded is None:
        return
    loaded_cassettes(node.config).update(loaded)


def session_finish(session: pytest.Session) -> None:
    """Check for orphaned cassettes at the end of the test session."""
    config = session.config
    loaded = loaded_cassettes(config)

    if is_xdist_worker(config):
        # Hand this shard's paths to the controller, which owns the reporting.
        cast(XdistWorkerConfig, config).workeroutput["vcr_loaded_cassettes"] = sorted(loaded)
        return

    orphan_dir = config.getoption("--vcr-check-orphans", default=None)
    if orphan_dir is None:
        return

    orphan_dir = os.path.abspath(orphan_dir)
    orphans = check_orphans(orphan_dir, loaded)

    if orphans:
        orphan_list = "\n  ".join(orphans)
        warnings.warn(
            f"Found {len(orphans)} orphaned cassette file(s) in {orphan_dir}:\n  {orphan_list}",
            OrphanedCassetteWarning,
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
