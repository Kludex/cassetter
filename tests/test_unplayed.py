from __future__ import annotations

import pytest

from cassetter._core import Body, WsFrame
from cassetter.cassette import Cassette
from cassetter.pytest_plugin.unplayed import resolve_on_unplayed, unplayed_interactions
from cassetter.recording import RecordMode

pytest_plugins = ("pytester",)

CONFTEST = """
import pytest
from cassetter._core import Body, Cassette, HttpInteraction, HttpRequest, HttpResponse

def _recorded(path):
    cassette = Cassette()
    for uri in ("https://api.example.com/one", "https://api.example.com/two"):
        cassette.add_interaction(
            HttpInteraction(HttpRequest("GET", uri), HttpResponse(200, body=Body("text", "ok")), "2026-01-01T00:00:00Z")
        )
    cassette.save(str(path))

@pytest.fixture(scope="module")
def vcr_config():
    return {"record_mode": "none", "on_unplayed": ON_UNPLAYED}

def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path.parent / "cassettes" / item.path.stem / (item.name + ".yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        _recorded(path)
"""

TESTS = """
import httpx
import pytest

@pytest.mark.vcr
def test_plays_one():
    httpx.get("https://api.example.com/one")

@pytest.mark.vcr
def test_plays_both():
    httpx.get("https://api.example.com/one")
    httpx.get("https://api.example.com/two")

@pytest.mark.vcr
def test_fails_itself():
    httpx.get("https://api.example.com/one")
    assert False, "the test's own failure"

@pytest.mark.vcr(on_unplayed="ignore")
def test_opts_out():
    httpx.get("https://api.example.com/one")
"""


def _run(pytester: pytest.Pytester, on_unplayed: str | None, *args: str) -> pytest.RunResult:
    pytester.makeconftest(CONFTEST.replace("ON_UNPLAYED", repr(on_unplayed)))
    pytester.makepyfile(test_unplayed=TESTS)
    return pytester.runpytest("-p", "no:cacheprovider", *args)


def test_fail_reports_unplayed_interactions_of_passing_tests(pytester: pytest.Pytester) -> None:
    result = _run(pytester, "fail")

    result.assert_outcomes(passed=3, failed=1, errors=1)
    result.stdout.fnmatch_lines(["*test_plays_one.yaml left interactions unplayed: HTTP [[]1[]]*"])
    # A test that already failed reports its own failure, not a second one about the cassette.
    result.stdout.fnmatch_lines(["*the test's own failure*"])
    assert "test_fails_itself.yaml left interactions unplayed" not in result.stdout.str()


def test_warn_reports_without_failing(pytester: pytest.Pytester) -> None:
    # The suite turns warnings into errors, which the inner run would inherit.
    result = _run(pytester, "warn", "-W", "default")

    result.assert_outcomes(passed=3, failed=1, warnings=1)
    result.stdout.fnmatch_lines(["*UnplayedInteractionsWarning: cassette *test_plays_one.yaml left*HTTP [[]1[]]*"])


def test_ignore_by_default(pytester: pytest.Pytester) -> None:
    result = _run(pytester, None)

    result.assert_outcomes(passed=3, failed=1)


def test_ini_option_applies_when_config_does_not_set_it(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nvcr_on_unplayed = fail\n")
    result = _run(pytester, None)

    result.assert_outcomes(passed=3, failed=1, errors=1)


def test_recording_cassettes_are_not_checked(pytester: pytest.Pytester) -> None:
    result = _run(pytester, "fail", "--record-mode=new_episodes")

    result.assert_outcomes(passed=3, failed=1)


BROKEN_TEARDOWN = """
import httpx
import pytest

@pytest.fixture
def breaks_on_teardown():
    yield
    raise RuntimeError("another fixture's teardown failed")

@pytest.mark.vcr
def test_plays_one(breaks_on_teardown):
    httpx.get("https://api.example.com/one")
"""


def test_a_teardown_failure_is_reported_alone(pytester: pytest.Pytester) -> None:
    """Another fixture failing after the cassette's own teardown still means the test didn't pass."""
    pytester.makeconftest(CONFTEST.replace("ON_UNPLAYED", repr("fail")))
    pytester.makepyfile(test_unplayed=BROKEN_TEARDOWN)
    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*another fixture's teardown failed*"])
    assert "left interactions unplayed" not in result.stdout.str()


def test_setup_only_runs_are_not_checked(pytester: pytest.Pytester) -> None:
    result = _run(pytester, "fail", "--setup-only")

    assert result.ret == 0
    assert "left interactions unplayed" not in result.stdout.str()


def test_invalid_action_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid on_unplayed: 'loud'"):
        resolve_on_unplayed({}, {"on_unplayed": "loud"}, None)


def test_marker_takes_precedence_over_config_and_ini() -> None:
    assert resolve_on_unplayed({"on_unplayed": "warn"}, {"on_unplayed": "fail"}, "ignore") == "warn"
    assert resolve_on_unplayed({}, {"on_unplayed": "fail"}, "ignore") == "fail"
    assert resolve_on_unplayed({}, None, "warn") == "warn"
    assert resolve_on_unplayed({}, None, None) == "ignore"


def test_unplayed_interactions_are_numbered_per_protocol() -> None:
    cassette = Cassette("unused.yaml", record_mode=RecordMode.NONE)
    cassette.record("GET", "https://api.example.com/one", {}, None, 200, {}, b"ok")
    cassette.record_ws("wss://ws.example.com", {}, [WsFrame("recv", "text", Body("text", "hi"), 0)])
    cassette.record_grpc(
        method="/pkg.Svc/Call", metadata={}, request_body=Body("binary", b"\x01"), response_body=Body("binary", b"\x02")
    )
    cassette.play("GET", "https://api.example.com/one", {}, None)
    cassette.play_ws("wss://ws.example.com")

    assert unplayed_interactions(cassette) == {"gRPC": [0]}
