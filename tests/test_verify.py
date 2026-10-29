from __future__ import annotations

import json
import os
import threading
import urllib.request
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aiohttp
import anyio
import httpx
import httpx2
import primp as pri
import pytest
import requests
import urllib3

from cassetter import (
    Compare,
    HttpResponse,
    NoMatchError,
    RawRequest,
    RecordMode,
    ResponseMismatchError,
    active_cassette,
    use_cassette,
)
from cassetter._core import Body

pytest_plugins = ("pytester",)


class Reply:
    def __init__(self) -> None:
        self.status = 200
        self.headers: dict[str, str] = {"content-type": "application/json"}
        self.body = b'{"answer": 42}'


@pytest.fixture
def reply() -> Reply:
    return Reply()


@pytest.fixture
def url(reply: Reply) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(reply.status)
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/answer"
    server.shutdown()
    server.server_close()


@pytest.fixture
def path(tmp_path: Path) -> str:
    return os.path.join(tmp_path, "verify.yaml")


def _httpx_async(url: str) -> None:
    async def get() -> None:
        async with httpx.AsyncClient() as client:
            await client.get(url)

    anyio.run(get)


def _httpx2_async(url: str) -> None:
    async def get() -> None:
        async with httpx2.AsyncClient() as client:
            await client.get(url)

    anyio.run(get)


def _aiohttp(url: str) -> None:
    async def get() -> None:
        async with aiohttp.ClientSession() as session, session.get(url) as response:
            await response.read()

    anyio.run(get)


CLIENTS: dict[str, tuple[str, Callable[[str], object]]] = {
    "httpx": ("httpx", httpx.get),
    "httpx-async": ("httpx", _httpx_async),
    "httpx2": ("httpx2", httpx2.get),
    "httpx2-async": ("httpx2", _httpx2_async),
    "requests": ("requests", requests.get),
    "urllib3": ("urllib3", lambda url: urllib3.PoolManager().request("GET", url)),
    "aiohttp": ("aiohttp", _aiohttp),
    "primp": ("primp", lambda url: pri.Client().get(url)),
}


@pytest.mark.parametrize("client", CLIENTS)
def test_verify_goes_live_and_compares(client: str, url: str, reply: Reply, path: str) -> None:
    intercept, get = CLIENTS[client]
    with use_cassette(path, record_mode="all", intercept=[intercept]):
        get(url)

    with use_cassette(path, record_mode="verify", intercept=[intercept]) as cassette:
        get(url)
    assert cassette.all_played

    reply.body = b'{"answer": 43}'
    with use_cassette(path, record_mode="verify", intercept=[intercept]):
        with pytest.raises(ResponseMismatchError, match=r'-  "answer": 42,?\n\+  "answer": 43'):
            get(url)


def test_verify_never_writes_the_cassette(url: str, reply: Reply, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)
    before = Path(path).read_text()

    with use_cassette(path, record_mode=RecordMode.VERIFY, intercept=["httpx"]):
        httpx.get(url)
    assert Path(path).read_text() == before


def test_verify_fails_without_a_match(url: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(NoMatchError):
            httpx.post(url)


def test_verify_compares_status(url: str, reply: Reply, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.status = 201
    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match="-status: 200\n\\+status: 201"):
            httpx.get(url)


def test_verify_compares_only_listed_headers(url: str, reply: Reply, path: str) -> None:
    reply.headers["x-price-estimate"] = "0.0001USD"
    reply.headers["x-request-id"] = "a"
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    compare = Compare(headers=["X-Price-*"])
    reply.headers["x-request-id"] = "b"
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=compare):
        httpx.get(url)

    reply.headers["x-price-estimate"] = "0.0002USD"
    expected = (
        f"cassette {path}, interaction 0 (GET {url})\n--- recorded\n+++ live\n"
        "@@ -1,6 +1,6 @@\n status: 200\n @@ headers @@\n"
        '-x-price-estimate: 0.0001USD\n+x-price-estimate: 0.0002USD\n @@ json body @@\n {\n   "answer": 42'
    )
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=compare):
        with pytest.raises(ResponseMismatchError) as exc_info:
            httpx.get(url)
    assert str(exc_info.value) == expected


def test_verify_ignores_json_paths_and_tolerates_floats(url: str, reply: Reply, path: str) -> None:
    reply.body = json.dumps({"id": "a", "items": [{"id": 1, "price": 0.1}], "total": 0.3}).encode()
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = json.dumps({"id": "b", "items": [{"id": 2, "price": 0.1}], "total": 0.1 + 0.2}).encode()
    compare = Compare(json_ignore=["id", "items[0].id"], float_tolerance=1e-9)
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=compare):
        httpx.get(url)

    with use_cassette(
        path, record_mode="verify", intercept=["httpx"], compare=Compare(json_ignore=["id"], float_tolerance=1e-9)
    ):
        with pytest.raises(
            ResponseMismatchError,
            match=r'-      "id": 1,\n\+      "id": 2,\n       "price": 0.1\n     }\n   \],$',
        ):
            httpx.get(url)


def test_verify_compares_sse_events_regardless_of_chunking(url: str, reply: Reply, path: str) -> None:
    reply.headers["content-type"] = "text/event-stream"
    reply.body = b'data: {"id": "a", "delta": "hel"}\n\ndata: {"id": "a", "delta": "lo"}\n\ndata: [DONE]\n\n'
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = (
        b': ping\n\ndata: {"id": "b",\ndata: "delta": "hel"}\r\n\r\ndata:{"id": "b", "delta": "lo"}\n\ndata: [DONE]\n\n'
    )
    compare = Compare(sse=True, json_ignore=["id"])
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=compare):
        httpx.get(url)

    reply.body = b'data: {"delta": "hello"}\n\ndata: [DONE]\n\n'
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=compare):
        with pytest.raises(ResponseMismatchError):
            httpx.get(url)

    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match=r'-data: {"id": "a", "delta": "hel"}\n'):
            httpx.get(url)


def test_verify_compares_binary_bodies(url: str, reply: Reply, path: str) -> None:
    reply.headers["content-type"] = "application/octet-stream"
    reply.body = b"\xff\x01"
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = b"\xff\x02"
    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match=r"-b'\\xff\\x01'\n\+b'\\xff\\x02'"):
            httpx.get(url)


def test_verify_before_compare_response_normalizes_both(url: str, reply: Reply, path: str) -> None:
    reply.body = b'{"answer": 42, "note": null}'
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    def drop_nulls(recorded: HttpResponse, live: HttpResponse) -> tuple[HttpResponse, HttpResponse]:
        def clean(response: HttpResponse) -> HttpResponse:
            content = {key: value for key, value in response.body.content.items() if value is not None}
            return response.replace(body=Body("json", content))

        return clean(recorded), clean(live)

    reply.body = b'{"answer": 42}'
    with use_cassette(path, record_mode="verify", intercept=["httpx"], before_compare_response=drop_nulls):
        httpx.get(url)


@pytest.fixture
def collector() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["content-length"]))
            headers = {name.lower(): [value] for name, value in self.headers.items()}
            cassette = active_cassette()
            assert cassette is not None
            cassette.observe(RawRequest("POST", f"http://collector{self.path}", headers, body))
            self.send_response(200)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _export(collector: str, body: bytes, delay: float = 0.0) -> None:
    """What the service under test does on its own: send telemetry the client never sees."""

    def send() -> None:
        request = urllib.request.Request(
            f"{collector}/v1/traces", data=body, headers={"content-type": "application/x-protobuf"}
        )
        urllib.request.urlopen(request).close()

    threading.Timer(delay, send).start()


def test_observed_requests_are_recorded_after_the_interactions(url: str, collector: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]) as cassette:
        httpx.get(url)
        _export(collector, b"\x0a\xff")
        for _ in range(500):
            if len(cassette) == 2:
                break
            threading.Event().wait(0.01)

    content = Path(path).read_text()
    assert content.index("interactions:") < content.index("observed_requests:\n- method: POST\n  uri: http://collector")
    assert "content: 0aff" in content


def test_verify_waits_for_observed_requests_and_compares_them(url: str, collector: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]) as cassette:
        httpx.get(url)
        cassette.observe(RawRequest("POST", "http://127.0.0.1:1/v1/traces", {}, b"\x0a\xff"))

    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        httpx.get(url)
        _export(collector, b"\x0a\xff", delay=0.2)

    decoded = Compare(decode=lambda raw: {"span": list(raw)})
    with pytest.raises(ResponseMismatchError, match=r"observed request 0\n(.*\n)*     10,\n-    255\n\+    254\n"):
        with use_cassette(path, record_mode="verify", intercept=["httpx"], observe_compare=decoded):
            httpx.get(url)
            _export(collector, b"\x0a\xfe")


def test_verify_fails_on_missing_observed_requests(url: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]) as cassette:
        httpx.get(url)
        cassette.observe(RawRequest("POST", "http://collector/v1/traces", {}, b"{}"))

    with pytest.raises(ResponseMismatchError, match="expected 1 observed requests, got 0"):
        with use_cassette(path, record_mode="verify", intercept=["httpx"], observe_timeout=0.05):
            httpx.get(url)


def test_replay_ignores_observed_requests(url: str, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)
    before = Path(path).read_text()

    with use_cassette(path, record_mode="none", intercept=["httpx"]) as cassette:
        httpx.get(url)
        cassette.observe(RawRequest("POST", "http://collector/v1/traces", {}, b"{}"))
    assert Path(path).read_text() == before
    assert "observed_requests" not in before


def test_pytest_plugin_checks_observed_requests(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
import pytest
from cassetter._core import Body, Cassette, HttpRequest

@pytest.fixture(scope="module")
def vcr_config():
    return {"observe_timeout": 2}

def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path.parent / "cassettes" / item.path.stem / (item.name + ".yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        cassette = Cassette()
        cassette.add_observed_request(HttpRequest("POST", "http://collector/v1/logs", body=Body("text", "x")))
        cassette.save(str(path))
"""
    )
    pytester.makepyfile(
        """
import pytest

import threading

from cassetter import RawRequest, active_cassette

@pytest.mark.vcr(record_mode="verify")
def test_service():
    pass

@pytest.mark.vcr(record_mode="verify")
def test_exports_after_the_body():
    request = RawRequest("POST", "http://collector/v1/logs", {"content-type": ["text/plain"]}, b"x")
    threading.Timer(0.1, lambda: active_cassette().observe(request)).start()

@pytest.mark.vcr(record_mode="verify")
def test_fails_itself():
    assert False, "the test's own failure"
"""
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=2, failed=1, errors=1)
    result.stdout.fnmatch_lines(["*ERROR at teardown of test_service*", "*expected 1 observed requests, got 0*"])
    assert "ERROR at teardown of test_fails_itself" not in result.stdout.str()


def test_verify_never_tolerates_a_status_change(url: str, reply: Reply, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.status = 201
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=Compare(float_tolerance=10)):
        with pytest.raises(ResponseMismatchError, match="-status: 200\n\\+status: 201"):
            httpx.get(url)


def test_verify_compares_trailing_newlines(url: str, reply: Reply, path: str) -> None:
    reply.headers["content-type"] = "text/plain"
    reply.body = b"answer\n"
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = b"answer"
    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match=r" answer\n-$"):
            httpx.get(url)


def test_verify_compares_body_types(url: str, reply: Reply, path: str) -> None:
    reply.body = b"null"
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.headers["content-type"] = "text/plain"
    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match="-@@ json body @@\n\\+@@ text body @@"):
            httpx.get(url)


def test_verify_compares_json_scalar_types(url: str, reply: Reply, path: str) -> None:
    reply.body = b'"1"'
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = b"1"
    with use_cassette(path, record_mode="verify", intercept=["httpx"]):
        with pytest.raises(ResponseMismatchError, match='-"1"\n\\+1$'):
            httpx.get(url)


def test_verify_ignores_array_elements(url: str, reply: Reply, path: str) -> None:
    reply.body = b'{"items": [1, 2]}'
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)

    reply.body = b'{"items": [3, 2]}'
    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=Compare(json_ignore=["items[0]"])):
        httpx.get(url)


def test_verify_compares_header_names_case_insensitively(url: str, reply: Reply, path: str) -> None:
    reply.headers["x-price-estimate"] = "0.0001USD"
    with use_cassette(path, record_mode="all", intercept=["httpx"]):
        httpx.get(url)
    Path(path).write_text(Path(path).read_text().replace("x-price-estimate", "X-Price-Estimate"))

    with use_cassette(path, record_mode="verify", intercept=["httpx"], compare=Compare(headers=["x-price-*"])):
        httpx.get(url)


def test_verify_mismatch_does_not_leak_scrubbed_query_parameters(url: str, reply: Reply, path: str) -> None:
    with use_cassette(path, record_mode="all", intercept=["httpx"], filter_query_parameters=["api_key"]):
        httpx.get(url, params={"api_key": "secret"})

    reply.status = 500
    with use_cassette(path, record_mode="verify", intercept=["httpx"], filter_query_parameters=["api_key"]):
        with pytest.raises(ResponseMismatchError) as exc_info:
            httpx.get(url, params={"api_key": "secret"})
    assert "secret" not in str(exc_info.value)
