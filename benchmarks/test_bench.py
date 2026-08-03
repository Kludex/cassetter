"""CodSpeed benchmarks for cassetter.

Run locally: uv run pytest benchmarks/test_bench.py --codspeed
"""

from __future__ import annotations

import tempfile

import pytest
from pytest_codspeed import BenchmarkFixture

from cassetter._core import (
    Body,
    Cassette,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    SecurityConfig,
    scrub_interaction,
)
from cassetter.cassette import Cassette as PyCassette
from cassetter.recording import RecordMode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_cassette(n: int) -> Cassette:
    c = Cassette()
    for i in range(n):
        c.add_interaction(
            HttpInteraction(
                request=HttpRequest(
                    "POST",
                    f"https://api.example.com/v1/items/{i}",
                    {
                        "accept": ["application/json"],
                        "content-type": ["application/json"],
                        "authorization": ["Bearer tok_abc123"],
                        "x-request-id": [f"req-{i:06d}"],
                    },
                    Body("json", {"id": i, "name": f"item-{i}", "tags": ["a", "b", "c"]}),
                ),
                response=HttpResponse(
                    200,
                    {
                        "content-type": ["application/json"],
                        "x-request-id": [f"req-{i:06d}"],
                        "cache-control": ["no-cache"],
                    },
                    Body(
                        "json",
                        {
                            "id": i,
                            "name": f"item-{i}",
                            "tags": ["a", "b", "c"],
                            "metadata": {"created": "2026-01-01", "version": 1},
                        },
                    ),
                ),
                recorded_at="2026-01-01T00:00:00Z",
            )
        )
    return c


@pytest.fixture(scope="module")
def cassette_100() -> Cassette:
    return _build_cassette(100)


@pytest.fixture(scope="module")
def cassette_1000() -> Cassette:
    return _build_cassette(1000)


@pytest.fixture(scope="module")
def yaml_file_100(cassette_100: Cassette) -> str:
    path = tempfile.mktemp(suffix=".yaml")
    cassette_100.save(path)
    return path


@pytest.fixture(scope="module")
def yaml_file_1000(cassette_1000: Cassette) -> str:
    path = tempfile.mktemp(suffix=".yaml")
    cassette_1000.save(path)
    return path


def _build_llm_cassette(n: int) -> Cassette:
    """LLM-shaped cassette: few interactions with large SSE/JSON bodies.

    This mirrors real recorded traffic (e.g. the pydantic-ai test corpus):
    load cost is dominated by large scalars rather than by event count,
    the opposite profile of `_build_cassette`.
    """
    sse_body = "".join(
        f'data: {{"id":"chatcmpl-abc","choices":[{{"delta":{{"content":"token {i} of a streamed completion"}}}}]}}\n\n'
        for i in range(400)
    )
    long_text = " ".join(f"word{i}" for i in range(2000))
    c = Cassette()
    for i in range(n):
        c.add_interaction(
            HttpInteraction(
                request=HttpRequest(
                    "POST",
                    "https://api.example.com/v1/chat/completions",
                    {"content-type": ["application/json"]},
                    Body(
                        "json",
                        {
                            "model": "gpt-5",
                            "stream": True,
                            "messages": [
                                {"role": "system", "content": long_text},
                                {"role": "user", "content": f"question {i}: {long_text}"},
                            ],
                        },
                    ),
                ),
                response=HttpResponse(
                    200,
                    {"content-type": ["text/event-stream"]},
                    Body("text", sse_body),
                ),
                recorded_at="2026-01-01T00:00:00Z",
            )
        )
    return c


@pytest.fixture(scope="module")
def llm_yaml_file(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("bench") / "llm.yaml")
    _build_llm_cassette(8).save(path)
    return path


@pytest.fixture(scope="module")
def toml_file_100(cassette_100: Cassette) -> str:
    path = tempfile.mktemp(suffix=".toml")
    cassette_100.save(path)
    return path


@pytest.fixture(scope="module")
def toml_file_1000(cassette_1000: Cassette) -> str:
    path = tempfile.mktemp(suffix=".toml")
    cassette_1000.save(path)
    return path


# ---------------------------------------------------------------------------
# Load benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_load_yaml_100(yaml_file_100: str, benchmark: BenchmarkFixture) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(yaml_file_100)


@pytest.mark.benchmark
def test_load_yaml_1000(yaml_file_1000: str, benchmark: BenchmarkFixture) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(yaml_file_1000)


@pytest.mark.benchmark
def test_load_yaml_llm_bodies(llm_yaml_file: str, benchmark: BenchmarkFixture) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(llm_yaml_file)


@pytest.mark.benchmark
def test_load_toml_100(toml_file_100: str, benchmark: BenchmarkFixture) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(toml_file_100)


@pytest.mark.benchmark
def test_load_toml_1000(toml_file_1000: str, benchmark: BenchmarkFixture) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(toml_file_1000)


# ---------------------------------------------------------------------------
# Save benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_save_yaml_100(cassette_100: Cassette, benchmark: BenchmarkFixture) -> None:
    path = tempfile.mktemp(suffix=".yaml")

    @benchmark
    def _() -> None:
        cassette_100.save(path)


@pytest.mark.benchmark
def test_save_yaml_1000(cassette_1000: Cassette, benchmark: BenchmarkFixture) -> None:
    path = tempfile.mktemp(suffix=".yaml")

    @benchmark
    def _() -> None:
        cassette_1000.save(path)


@pytest.mark.benchmark
def test_save_toml_100(cassette_100: Cassette, benchmark: BenchmarkFixture) -> None:
    path = tempfile.mktemp(suffix=".toml")

    @benchmark
    def _() -> None:
        cassette_100.save(path)


@pytest.mark.benchmark
def test_save_toml_1000(cassette_1000: Cassette, benchmark: BenchmarkFixture) -> None:
    path = tempfile.mktemp(suffix=".toml")

    @benchmark
    def _() -> None:
        cassette_1000.save(path)


# ---------------------------------------------------------------------------
# Match benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_match_first_100(cassette_100: Cassette, benchmark: BenchmarkFixture) -> None:
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/0")

    @benchmark
    def _() -> None:
        cassette_100.take_match(req, config)


@pytest.mark.benchmark
def test_match_last_1000(cassette_1000: Cassette, benchmark: BenchmarkFixture) -> None:
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/999")

    @benchmark
    def _() -> None:
        cassette_1000.take_match(req, config)


@pytest.mark.benchmark
def test_match_miss_1000(cassette_1000: Cassette, benchmark: BenchmarkFixture) -> None:
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/99999")

    @benchmark
    def _() -> None:
        cassette_1000.take_match(req, config)


# ---------------------------------------------------------------------------
# Security scrub benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_scrub_interaction(benchmark: BenchmarkFixture) -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/v1/data?api_key=secret&format=json",
            {"authorization": ["Bearer tok"], "content-type": ["application/json"]},
            Body("json", {"password": "secret", "data": "hello"}),
        ),
        response=HttpResponse(
            200,
            {"set-cookie": ["session=abc"], "content-type": ["application/json"]},
            Body("json", {"access_token": "tok_abc", "result": "ok"}),
        ),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()

    @benchmark
    def _() -> None:
        scrub_interaction(interaction, config)


# ---------------------------------------------------------------------------
# Full replay path
# ---------------------------------------------------------------------------
#
# This is the function every interceptor calls, so it is the number a test
# suite actually feels. Benchmarking the raw matcher alone hid the cost of
# everything around it.


@pytest.fixture
def replay_cassette_100(yaml_file_100: str) -> PyCassette:
    cassette = PyCassette(yaml_file_100, record_mode=RecordMode.NONE)
    cassette.load()
    return cassette


@pytest.mark.benchmark
def test_replay_via_play_100(replay_cassette_100: PyCassette, benchmark: BenchmarkFixture) -> None:
    headers = {"accept": ["application/json"]}

    @benchmark
    def _() -> None:
        replay_cassette_100.play("POST", "https://api.example.com/v1/items/99", headers, None)


# ---------------------------------------------------------------------------
# Text and SSE scrubbing
# ---------------------------------------------------------------------------
#
# The JSON-body benchmark above never exercises the text path, which is where
# streaming responses land.


def _text_interaction(body: str) -> HttpInteraction:
    return HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/v1/chat",
            {"content-type": ["application/x-www-form-urlencoded"]},
            Body("text", "grant_type=password&password=hunter2&client_id=abc"),
        ),
        response=HttpResponse(200, {"content-type": ["text/event-stream"]}, Body("text", body)),
        recorded_at="2026-01-01T00:00:00Z",
    )


@pytest.mark.benchmark
def test_scrub_text_bodies(benchmark: BenchmarkFixture) -> None:
    interaction = _text_interaction('{"access_token": "tok_abc", "result": "ok"}')
    config = SecurityConfig()

    @benchmark
    def _() -> None:
        scrub_interaction(interaction, config)


@pytest.mark.benchmark
def test_scrub_sse_stream(benchmark: BenchmarkFixture) -> None:
    chunks = "".join(f'data: {{"i": {i}, "access_token": "tok_{i}"}}\n\n' for i in range(50))
    interaction = _text_interaction(chunks + "data: [DONE]\n\n")
    config = SecurityConfig()

    @benchmark
    def _() -> None:
        scrub_interaction(interaction, config)
