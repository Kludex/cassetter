"""CodSpeed benchmarks for cassetter.

Run locally: uv run pytest benchmarks/test_bench.py --codspeed
"""

from __future__ import annotations

import tempfile
from typing import Any

import pytest

from cassetter._core import (
    Body,
    Cassette,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    SecurityConfig,
    find_match,
    scrub_interaction,
)

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
def test_load_yaml_100(yaml_file_100: str, benchmark: Any) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(yaml_file_100)


@pytest.mark.benchmark
def test_load_yaml_1000(yaml_file_1000: str, benchmark: Any) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(yaml_file_1000)


@pytest.mark.benchmark
def test_load_yaml_llm_bodies(llm_yaml_file: str, benchmark: Any) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(llm_yaml_file)


@pytest.mark.benchmark
def test_load_toml_100(toml_file_100: str, benchmark: Any) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(toml_file_100)


@pytest.mark.benchmark
def test_load_toml_1000(toml_file_1000: str, benchmark: Any) -> None:
    @benchmark
    def _() -> None:
        Cassette.load(toml_file_1000)


# ---------------------------------------------------------------------------
# Save benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_save_yaml_100(cassette_100: Cassette, benchmark: Any) -> None:
    path = tempfile.mktemp(suffix=".yaml")

    @benchmark
    def _() -> None:
        cassette_100.save(path)


@pytest.mark.benchmark
def test_save_yaml_1000(cassette_1000: Cassette, benchmark: Any) -> None:
    path = tempfile.mktemp(suffix=".yaml")

    @benchmark
    def _() -> None:
        cassette_1000.save(path)


@pytest.mark.benchmark
def test_save_toml_100(cassette_100: Cassette, benchmark: Any) -> None:
    path = tempfile.mktemp(suffix=".toml")

    @benchmark
    def _() -> None:
        cassette_100.save(path)


@pytest.mark.benchmark
def test_save_toml_1000(cassette_1000: Cassette, benchmark: Any) -> None:
    path = tempfile.mktemp(suffix=".toml")

    @benchmark
    def _() -> None:
        cassette_1000.save(path)


# ---------------------------------------------------------------------------
# Match benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_match_first_100(cassette_100: Cassette, benchmark: Any) -> None:
    interactions = cassette_100.interactions
    played = [False] * len(interactions)
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/0")

    @benchmark
    def _() -> None:
        find_match(req, interactions, played, config)


@pytest.mark.benchmark
def test_match_last_1000(cassette_1000: Cassette, benchmark: Any) -> None:
    interactions = cassette_1000.interactions
    played = [False] * len(interactions)
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/999")

    @benchmark
    def _() -> None:
        find_match(req, interactions, played, config)


@pytest.mark.benchmark
def test_match_miss_1000(cassette_1000: Cassette, benchmark: Any) -> None:
    interactions = cassette_1000.interactions
    played = [False] * len(interactions)
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/99999")

    @benchmark
    def _() -> None:
        try:
            find_match(req, interactions, played, config)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Security scrub benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_scrub_interaction(benchmark: Any) -> None:
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
