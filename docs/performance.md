# Performance

Cassette parsing, matching, and serialization run in Rust, through a PyO3 extension module. There is no Python level YAML parsing at all.

## Benchmarks

Compared with VCR.py (using its fastest configuration, PyYAML with libyaml):

```
                cassetter    vcrpy       speedup
10 interactions
load            192 us       480 us      2.5x
match           0.9 us       12.3 us     13.2x
save            250 us       477 us      1.9x

1000 interactions
load            16.7 ms      53.9 ms     3.2x
match           0.8 us       1.25 ms     1527.1x
save            6.6 ms       47.0 ms     7.2x
```

Absolute timings are machine dependent, so the speedup ratios matter more than the raw numbers. Load speedup also depends on cassette shape. Many tiny interactions (as above) is the cheapest shape per byte, because the parser spends most of its time on structure it handles well. A cassette dominated by large bodies - LLM and SSE responses, for example - is the opposite profile: parsing is one long scalar copy, which neither parser can shortcut, so the margin narrows to roughly 2.5x.

TOML cassettes load about 4.3 times faster than YAML, save about 2.4 times faster, and produce about 12% smaller files:

```
                YAML         TOML
save            10.2 ms      4.3 ms
load            26.1 ms      6.0 ms
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
