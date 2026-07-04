# Performance

Cassette parsing, matching, and serialization run in Rust, through a PyO3 extension module. There is no Python level YAML parsing at all.

## Benchmarks

Compared with VCR.py (which uses PyYAML with libyaml), on a cassette with 1000 interactions:

```
                cassetter    vcrpy       speedup
load            13.53 ms     58.90 ms    4.4x
match           0.98 ms      1.29 ms     1.3x
save            7.58 ms      45.64 ms    6.0x
```

TOML cassettes load about 2 times faster than YAML and produce about 12% smaller files:

```
                YAML         TOML
save            10.59 ms     11.67 ms
load            18.99 ms     9.79 ms
size            768.0 KB     675.3 KB
```

## Why it matters

A single cassette load taking 50 ms sounds harmless. Now multiply it by 500 tests, each loading a cassette in its setup. That is 25 seconds of pure parsing overhead per test run, before a single assertion executes.

At Cassetter's speed the same suite spends about 7 seconds parsing, and switching the large cassettes to TOML brings it further down.

## Reproduce the numbers

The benchmarks live in the repository and run against your machine:

```console
$ uv run python benchmarks/bench.py
$ uv run python benchmarks/bench_formats.py
```

They are also tracked continuously in CI with CodSpeed, so performance regressions show up in pull requests.
