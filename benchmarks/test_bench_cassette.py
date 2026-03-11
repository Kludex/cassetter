"""Pytest-codspeed benchmarks for cassetter core operations."""

from __future__ import annotations

import tempfile

import pytest

from cassetter._core import (
    Cassette,
    HttpRequest,
    MatchConfig,
    find_match,
)

# ---------------------------------------------------------------------------
# Load benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_load_yaml_100(yaml_cassette_100: str) -> None:
    Cassette.load(yaml_cassette_100)


@pytest.mark.benchmark
def test_load_yaml_1000(yaml_cassette_1000: str) -> None:
    Cassette.load(yaml_cassette_1000)


@pytest.mark.benchmark
def test_load_toml_100(toml_cassette_100: str) -> None:
    Cassette.load(toml_cassette_100)


@pytest.mark.benchmark
def test_load_toml_1000(toml_cassette_1000: str) -> None:
    Cassette.load(toml_cassette_1000)


# ---------------------------------------------------------------------------
# Save benchmarks
# ---------------------------------------------------------------------------


def test_save_yaml_100(benchmark, cassette_obj_100: Cassette) -> None:
    path = tempfile.mktemp(suffix=".yaml")
    benchmark(cassette_obj_100.save, path)


def test_save_yaml_1000(benchmark, cassette_obj_1000: Cassette) -> None:
    path = tempfile.mktemp(suffix=".yaml")
    benchmark(cassette_obj_1000.save, path)


def test_save_toml_100(benchmark, cassette_obj_100: Cassette) -> None:
    path = tempfile.mktemp(suffix=".toml")
    benchmark(cassette_obj_100.save, path)


def test_save_toml_1000(benchmark, cassette_obj_1000: Cassette) -> None:
    path = tempfile.mktemp(suffix=".toml")
    benchmark(cassette_obj_1000.save, path)


# ---------------------------------------------------------------------------
# Match benchmarks (worst-case: match the last interaction)
# ---------------------------------------------------------------------------


def test_match_100(benchmark, yaml_cassette_100: str) -> None:
    cassette = Cassette.load(yaml_cassette_100)
    interactions = cassette.interactions
    played = [False] * len(interactions)
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/99")

    benchmark(find_match, req, interactions, played, config)


def test_match_1000(benchmark, yaml_cassette_1000: str) -> None:
    cassette = Cassette.load(yaml_cassette_1000)
    interactions = cassette.interactions
    played = [False] * len(interactions)
    config = MatchConfig()
    req = HttpRequest("POST", "https://api.example.com/v1/items/999")

    benchmark(find_match, req, interactions, played, config)
