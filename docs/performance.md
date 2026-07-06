# Performance

Cassette parsing, matching, and serialization run in Rust, through a PyO3 extension module. There is no Python level YAML parsing at all.

## Benchmarks

Compared with VCR.py (using its fastest configuration, PyYAML with libyaml), on a cassette with 1000 interactions:

```
                cassetter    vcrpy       speedup
load            35 ms        96 ms       2.7x
match           1.3 ms       1.85 ms     1.4x
save            6.5 ms       77 ms       11.8x
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

Saves are 7 to 12 times faster than VCR.py, which matters when you re-record. Loads run on every test: a cassette-heavy suite that spends seconds in VCR.py's parser spends a fraction of that here, and switching large cassettes to TOML cuts load time further.

## Reproduce the numbers

The benchmarks live in the repository and run against your machine:

```console
$ uv run python benchmarks/bench.py
$ uv run python benchmarks/bench_formats.py
```

They are also tracked continuously in CI with CodSpeed, so performance regressions show up in pull requests.
