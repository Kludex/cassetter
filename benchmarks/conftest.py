from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cassetter._core import (
    Body,
    Cassette,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
)


def _build_cassette(n: int) -> Cassette:
    """Build a Cassette with *n* HTTP interactions."""
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


@pytest.fixture(scope="session")
def tmp_bench_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="session")
def yaml_cassette_100(tmp_bench_dir: Path) -> str:
    path = str(tmp_bench_dir / "cassette_100.yaml")
    _build_cassette(100).save(path)
    return path


@pytest.fixture(scope="session")
def yaml_cassette_1000(tmp_bench_dir: Path) -> str:
    path = str(tmp_bench_dir / "cassette_1000.yaml")
    _build_cassette(1000).save(path)
    return path


@pytest.fixture(scope="session")
def toml_cassette_100(tmp_bench_dir: Path) -> str:
    path = str(tmp_bench_dir / "cassette_100.toml")
    _build_cassette(100).save(path)
    return path


@pytest.fixture(scope="session")
def toml_cassette_1000(tmp_bench_dir: Path) -> str:
    path = str(tmp_bench_dir / "cassette_1000.toml")
    _build_cassette(1000).save(path)
    return path


@pytest.fixture(scope="session")
def cassette_obj_100() -> Cassette:
    return _build_cassette(100)


@pytest.fixture(scope="session")
def cassette_obj_1000() -> Cassette:
    return _build_cassette(1000)
