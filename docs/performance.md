# Performance

Cassette parsing, matching, and serialization run in Rust, through a PyO3 extension module. There is no Python level YAML parsing at all.

## Benchmarks

Compared with VCR.py (using its fastest configuration, PyYAML with libyaml):

```
                cassetter    vcrpy       speedup
10 interactions
load            205 us       471 us      2.3x
match           0.9 us       12.6 us     13.7x
save            252 us       456 us      1.8x

1000 interactions
load            18.1 ms      52.8 ms     2.9x
match           0.8 us       1.22 ms     1573.7x
save            6.5 ms       42.5 ms     6.5x
```

Absolute timings are machine dependent, so the speedup ratios matter more than the raw numbers. Load speedup also depends on cassette shape: many tiny interactions (as above) is the hardest case for the parser, while cassettes dominated by large bodies - LLM and SSE responses, for example - load proportionally faster.

TOML cassettes load about 2.8 times faster than YAML and produce about 12% smaller files, at the cost of slower saves:

```
                YAML         TOML
save            10.7 ms      18.0 ms
load            53 ms        18.6 ms
size            768 KB       675 KB
```

## Why it matters

Matching runs once per request; load and save run once per test. On a 1000 interaction cassette, replaying every interaction costs under a millisecond in total, against roughly 1.2 seconds under VCR.py - the gap that dominates a cassette-heavy suite.

Two things make match cost independent of cassette size:

- The method+URI index is built once and cached on the cassette, not rebuilt per lookup.
- Matching runs inside Rust against the interactions it already owns. Handing interactions back and forth across the FFI boundary would copy the whole cassette on every request, which costs more than the matching itself.

Re-recording benefits from the faster saves, and switching large cassettes to TOML cuts load time further.

## Reproduce the numbers

The benchmarks live in the repository and run against your machine:

```console
$ uv run python benchmarks/bench.py
$ uv run python benchmarks/bench_formats.py
```

They are also tracked continuously in CI with CodSpeed, so performance regressions show up in pull requests. `test_replay_via_play_100` covers the full public replay path, and the scrub benchmarks cover JSON, form encoded and SSE bodies, so a regression in any of them is visible.
