from __future__ import annotations

import pytest

pytest_plugins = ("pytester",)

CONFTEST = """
import pytest

from cassetter import Body, HttpInteraction, HttpRequest, HttpResponse
from cassetter._core import Cassette

HEADERS = {"content-type": ["application/json"]}

@pytest.fixture(scope="module")
def vcr_config():
    return {"record_mode": "none", "decode_compressed_response": True}


@pytest.fixture(scope="module", autouse=True)
def recorded(request):
    cassette = Cassette()
    cassette.add_interaction(
        HttpInteraction(
            HttpRequest("POST", "https://api.example.com/chat", HEADERS, Body("json", {"a": 1})),
            HttpResponse(200, body=Body("text", "ok")),
            "2026-01-01T00:00:00Z",
        )
    )
    directory = request.path.parent / "cassettes" / request.path.stem
    for name in ("test_same_body.yaml", "test_different_body.yaml", "test_body_without_matcher.yaml"):
        cassette.save(str(directory / name))
"""

TEST_MODULE = """
import pytest

from cassetter import NoMatchError

HEADERS = {"content-type": ["application/json"]}


@pytest.mark.vcr(ignore_hosts=["gateway.example"])
def test_ignore_hosts(vcr):
    assert vcr.should_bypass("https://gateway.example/test")


@pytest.mark.vcr(additional_matchers=["body"])
def test_same_body(vcr):
    assert vcr.play("POST", "https://api.example.com/chat", HEADERS, b'{"a": 1}').status == 200


@pytest.mark.vcr(additional_matchers=["body"])
def test_different_body(vcr):
    with pytest.raises(NoMatchError):
        vcr.play("POST", "https://api.example.com/chat", HEADERS, b'{"completely": "different"}')


@pytest.mark.vcr
def test_body_without_matcher(vcr):
    assert vcr.play("POST", "https://api.example.com/chat", HEADERS, b'{"completely": "different"}').status == 200


@pytest.mark.vcr(decode_compressed_response=True)
def test_unsupported_option(vcr):
    pass
"""


def test_marker_options(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_markers=TEST_MODULE)

    result = pytester.runpytest()

    result.assert_outcomes(passed=4, errors=1)
    result.stdout.fnmatch_lines(["*TypeError: unsupported @pytest.mark.vcr options: decode_compressed_response"])
