"""A crashed xdist worker must not abort the whole session.

`pytest_testnodedown` fires for every worker that goes away, including one
that died mid-run (segfault, `os._exit`, a timeout plugin killing it). Such a
worker never sent its `workeroutput`, so reading it raised AttributeError
inside the hook, which pytest reports as INTERNALERROR and the run ends
without a summary - the one crash hides every other result.
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
import os
import pytest

@pytest.mark.vcr
def test_survivor():
    pass

def test_crashes_its_worker():
    os._exit(1)
"""


@pytest.fixture
def crashing_project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_a=TEST_MODULE)
    pytester.mkdir("cassettes")
    return pytester


def test_crashed_worker_does_not_abort_the_session(crashing_project: pytest.Pytester) -> None:
    result = crashing_project.runpytest_subprocess(
        "-n", "2", "--vcr-check-orphans", "cassettes", "--max-worker-restart", "0"
    )

    assert "INTERNALERROR" not in result.stdout.str()
    assert "INTERNALERROR" not in result.stderr.str()
    # the crash itself is still reported by xdist, and the surviving test still counts
    result.stdout.fnmatch_lines(["*test_crashes_its_worker*"])
    result.assert_outcomes(passed=1, failed=1)
