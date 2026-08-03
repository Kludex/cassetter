"""Benchmark: cassetter (Rust/PyO3) vs vcrpy (pure Python).

Usage: uv run python benchmarks/bench.py
"""

from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

import yaml
from vcr.cassette import Cassette as VcrpyCassette
from vcr.request import Request as VcrpyRequest

from cassetter._core import (
    Body,
    Cassette as RustCassette,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
)

ITERATIONS = 20
TRIM = 4  # drop 2 lowest + 2 highest for trimmed mean
SCALES = [10, 100, 1000]


def trimmed_mean(times: list[float]) -> float:
    s = sorted(times)
    trimmed = s[TRIM // 2 : len(s) - TRIM // 2]
    return statistics.mean(trimmed)


# ---------------------------------------------------------------------------
# Cassette generators
# ---------------------------------------------------------------------------


def generate_cassetter_cassette(path: str, n: int) -> None:
    c = RustCassette()
    for i in range(n):
        c.add_interaction(
            HttpInteraction(
                request=HttpRequest(
                    "GET",
                    f"https://api.example.com/items/{i}",
                    {"content-type": ["application/json"], "authorization": ["Bearer tok"]},
                    Body("json", {"query": f"item_{i}"}),
                ),
                response=HttpResponse(
                    200,
                    {"content-type": ["application/json"]},
                    Body("json", {"id": i, "name": f"Item {i}", "tags": ["a", "b"]}),
                ),
                recorded_at="2026-01-01T00:00:00Z",
            )
        )
    c.save(path)


def generate_vcrpy_cassette(path: str, n: int) -> None:
    c = VcrpyCassette(path)
    for i in range(n):
        req = VcrpyRequest(
            "GET",
            f"https://api.example.com/items/{i}",
            '{"query": "item_' + str(i) + '"}',
            {"content-type": "application/json", "authorization": "Bearer tok"},
        )
        resp = {
            "status": {"code": 200, "message": "OK"},
            "headers": {"content-type": ["application/json"]},
            "body": {"string": '{"id": ' + str(i) + ', "name": "Item ' + str(i) + '", "tags": ["a", "b"]}'},
        }
        c.append(req, resp)
    c.dirty = True
    c._save(force=True)


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


def bench(fn: object, iterations: int = ITERATIONS) -> float:
    """Return trimmed-mean elapsed time in seconds."""
    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()  # type: ignore[operator]
        times.append(time.perf_counter() - start)
    return trimmed_mean(times)


def fmt_ms(seconds: float) -> str:
    ms = seconds * 1000
    if ms >= 1:
        return f"{ms:.2f} ms"
    us = seconds * 1_000_000
    return f"{us:.1f} us"


# ---------------------------------------------------------------------------
# Benchmarks per scale
# ---------------------------------------------------------------------------


def run_scale(n: int, tmpdir: Path) -> list[tuple[str, float, float]]:
    vbb_path = str(tmpdir / f"vbb_{n}.yaml")
    vcrpy_path = str(tmpdir / f"vcrpy_{n}.yaml")

    generate_cassetter_cassette(vbb_path, n)
    generate_vcrpy_cassette(vcrpy_path, n)

    results: list[tuple[str, float, float]] = []

    # -- Load ------------------------------------------------------------------
    def load_vbb() -> None:
        RustCassette.load(vbb_path)

    def load_vcrpy() -> None:
        VcrpyCassette.load(path=vcrpy_path, allow_playback_repeats=True)

    results.append(("load", bench(load_vbb), bench(load_vcrpy)))

    # -- Match (worst-case for linear scan: match the last item) ---------------
    last_uri = f"https://api.example.com/items/{n - 1}"

    # Both sides go through the public replay entry point. Nothing is hoisted
    # out of the timed region: lookup cost per request is what a test suite
    # actually pays, and hoisting it hid that cost entirely.
    vbb_cassette = RustCassette.load(vbb_path)
    config = MatchConfig()
    vbb_req = HttpRequest("GET", last_uri)

    def match_vbb() -> None:
        vbb_cassette.take_match(vbb_req, config)

    vcrpy_cassette = VcrpyCassette.load(path=vcrpy_path, allow_playback_repeats=True)
    vcrpy_req = VcrpyRequest("GET", last_uri, "", {})

    def match_vcrpy() -> None:
        vcrpy_cassette.play_response(vcrpy_req)

    results.append(("match", bench(match_vbb), bench(match_vcrpy)))

    # -- Save ------------------------------------------------------------------
    vbb_save_path = str(tmpdir / f"vbb_save_{n}.yaml")
    source_vbb = RustCassette.load(vbb_path)

    def save_vbb() -> None:
        source_vbb.save(vbb_save_path)

    source_vcrpy = VcrpyCassette.load(path=vcrpy_path, allow_playback_repeats=True)

    def save_vcrpy() -> None:
        source_vcrpy.dirty = True
        source_vcrpy._save(force=True)

    results.append(("save", bench(save_vbb), bench(save_vcrpy)))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def detect_yaml_backend() -> str:
    if yaml.__with_libyaml__:
        return "libyaml (C)"
    return "PyYAML (pure Python)"


def main() -> None:
    print("cassetter vs vcrpy benchmark")
    print("=" * 40)
    print(f"yaml: {detect_yaml_backend()}")
    print(f"iterations: {ITERATIONS} (trimmed mean, drop {TRIM})")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        for n in SCALES:
            print(f"  {n} interactions")
            header = f"  {'':18s}{'cassetter':>16s}{'vcrpy':>16s}{'speedup':>12s}"
            print(header)

            results = run_scale(n, Path(tmpdir))
            for name, vbb_time, vcrpy_time in results:
                speedup = vcrpy_time / vbb_time if vbb_time > 0 else float("inf")
                print(f"  {name:18s}{fmt_ms(vbb_time):>16s}{fmt_ms(vcrpy_time):>16s}{speedup:>10.1f}x")
            print()


if __name__ == "__main__":
    main()
