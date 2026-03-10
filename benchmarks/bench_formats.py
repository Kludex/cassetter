"""Benchmark cassette load/save across YAML, TOML, and VCR formats."""

from __future__ import annotations

import os
import tempfile
import time

from cassetter._core import Body, Cassette, HttpInteraction, HttpRequest, HttpResponse


def build_cassette(n: int) -> Cassette:
    """Build a cassette with *n* HTTP interactions."""
    c = Cassette()
    for i in range(n):
        c.add_interaction(
            HttpInteraction(
                HttpRequest(
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
                HttpResponse(
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
                "2026-01-01T00:00:00Z",
            )
        )
    return c


def bench_format(cassette: Cassette, ext: str, rounds: int = 20) -> dict[str, float]:
    """Benchmark save then load for a given file extension."""
    path = tempfile.mktemp(suffix=f".{ext}")

    # Warmup
    cassette.save(path)
    Cassette.load(path)

    # Save benchmark
    save_times: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        cassette.save(path)
        save_times.append(time.perf_counter() - t0)

    file_size = os.path.getsize(path)

    # Load benchmark
    load_times: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        Cassette.load(path)
        load_times.append(time.perf_counter() - t0)

    os.unlink(path)

    return {
        "save_ms": sum(save_times) / len(save_times) * 1000,
        "load_ms": sum(load_times) / len(load_times) * 1000,
        "size_kb": file_size / 1024,
    }


def main() -> None:
    for n in (50, 200, 1000):
        cassette = build_cassette(n)
        print(f"\n{'=' * 60}")
        print(f"  {n} interactions")
        print(f"{'=' * 60}")
        print(f"{'Format':<10} {'Save (ms)':>10} {'Load (ms)':>10} {'Size (KB)':>10}")
        print(f"{'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10}")

        for ext, label in [("yaml", "YAML"), ("toml", "TOML")]:
            result = bench_format(cassette, ext)
            print(f"{label:<10} {result['save_ms']:>10.2f} {result['load_ms']:>10.2f} {result['size_kb']:>10.1f}")


if __name__ == "__main__":
    main()
