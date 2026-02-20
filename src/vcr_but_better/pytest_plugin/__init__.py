from __future__ import annotations

from vcr_but_better.pytest_plugin.fixtures import vcr_cassette as vcr_cassette, vcr_config as vcr_config
from vcr_but_better.pytest_plugin.markers import configure as configure
from vcr_but_better.pytest_plugin.orphans import check_orphans as check_orphans

__all__ = ["vcr_cassette", "vcr_config", "configure", "check_orphans"]


def pytest_configure(config: object) -> None:
    configure(config)


def pytest_addoption(parser: object) -> None:
    from vcr_but_better.pytest_plugin.orphans import add_options

    add_options(parser)


def pytest_collection_modifyitems(items: list[object]) -> None:
    """Auto-request the vcr_cassette fixture for tests marked with @pytest.mark.vcr."""
    import pytest

    for item in items:
        assert isinstance(item, pytest.Item)
        if item.get_closest_marker("vcr") is not None and isinstance(item, pytest.Function):
            # Only add if not already explicitly requested
            if "vcr_cassette" not in item.fixturenames:
                item.fixturenames.append("vcr_cassette")


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    from vcr_but_better.pytest_plugin.orphans import session_finish

    session_finish(session)
