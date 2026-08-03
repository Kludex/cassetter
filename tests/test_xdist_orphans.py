"""Orphan detection must aggregate across pytest-xdist workers.

Each worker runs its own `pytest_sessionfinish` and only sees the tests in its
own shard, so without aggregation the controller reports every cassette the
other workers loaded as an orphan - a failed run on a clean directory.
"""

from __future__ import annotations

import pytest

pytest_plugins = ("pytester",)

CONFTEST = """
import pytest

@pytest.fixture(scope="module")
def vcr_config():
    return {"record_mode": "all"}
"""

TEST_MODULE = """
import pytest

@pytest.mark.vcr
def test_one():
    pass

@pytest.mark.vcr
def test_two():
    pass
"""


@pytest.fixture
def orphan_project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_a=TEST_MODULE)
    pytester.mkdir("cassettes")
    return pytester


def test_no_false_orphans_serial(orphan_project: pytest.Pytester) -> None:
    result = orphan_project.runpytest_subprocess("--vcr-check-orphans", "cassettes", "-W", "error")
    result.assert_outcomes(passed=2)


def test_no_false_orphans_under_xdist(orphan_project: pytest.Pytester) -> None:
    """A clean cassette directory must not fail the run just because -n was used."""
    result = orphan_project.runpytest_subprocess("-n", "2", "--vcr-check-orphans", "cassettes", "-W", "error")
    result.assert_outcomes(passed=2)
    assert "orphaned cassette" not in result.stdout.str()


def test_real_orphan_is_still_reported_under_xdist(orphan_project: pytest.Pytester) -> None:
    orphan_project.path.joinpath("cassettes", "orphan_here.yaml").write_text("---")

    result = orphan_project.runpytest_subprocess("-n", "2", "--vcr-check-orphans", "cassettes")

    result.stdout.fnmatch_lines(["*OrphanedCassetteWarning: Found 1 orphaned cassette file(s)*", "*orphan_here.yaml*"])
