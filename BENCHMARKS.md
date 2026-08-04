# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-5` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.

Results were collected on an Apple M5 Max with 128 GB of memory and eight build jobs. Both toolchains
use the same source revision, default development profiles, and separate Cargo target directories.
Dependencies are cached before timing begins. Samples contaminated by concurrent builds are
discarded.

- **Cold:** One build from an empty target directory.
- **Dependency edit:** Median of seven implementation-only edits to a shared dependency.
- **Direct edit:** Median of five implementation-only edits to the target crate.
- **No-op:** Median of three runs without source changes.

Each test workflow builds and runs one existing unit test. Codex normally pins Rust 1.95.0; these
benchmarks use Rust 1.97.1 for both projects to match Ohm's Rust base.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     38.72 s | 37.94 s |   1.02× |
| Dependency edit, `check`  |      4.62 s |  0.32 s |  14.38× |
| Direct edit, `check`      |      0.92 s |  1.11 s |   0.82× |
| No-op `cargo check`       |      0.28 s |  0.22 s |   1.27× |
| Cold `cargo clippy`       |     38.87 s | 37.64 s |   1.03× |
| Dependency edit, `clippy` |      8.63 s |  0.34 s |  25.04× |
| Direct edit, `clippy`     |      1.96 s |  1.57 s |   1.25× |
| No-op `cargo clippy`      |      0.29 s |  0.26 s |   1.12× |
| Cold `cargo test`         |     60.44 s | 70.71 s |   0.85× |
| Dependency edit, `test`   |      9.23 s |  1.10 s |   8.42× |
| Direct edit, `test`       |      2.73 s |  3.08 s |   0.88× |
| No-op `cargo test`        |      0.30 s |  0.23 s |   1.31× |

The measured commands are:

```console
cargo +1.97.1 check -p uv --lib --locked --offline
cargo +1.97.1 clippy -p uv --lib --locked --offline
cargo +1.97.1 test -p uv --lib --locked --offline \
  install_source::tests::detects_homebrew_cellar -- --exact
```

Replace `+1.97.1` with `+ohm` to run the Ohm variants.

## Codex: codex-tools

These benchmarks target the `codex-tools` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-tools` itself.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     40.37 s | 42.89 s |   0.94× |
| Dependency edit, `check`  |      4.51 s |  0.43 s |  10.61× |
| Direct edit, `check`      |      0.71 s |  0.59 s |   1.21× |
| No-op `cargo check`       |      0.47 s |  0.36 s |   1.30× |
| Cold `just clippy`        |     47.25 s | 45.02 s |   1.05× |
| Dependency edit, `clippy` |      8.69 s |  0.53 s |  16.49× |
| Direct edit, `clippy`     |      1.07 s |  0.76 s |   1.40× |
| No-op `just clippy`       |      0.57 s |  0.45 s |   1.26× |
| Cold `just test`          |     57.35 s | 63.83 s |   0.90× |
| Dependency edit, `test`   |      8.30 s |  1.67 s |   4.97× |
| Direct edit, `test`       |      2.36 s |  2.32 s |   1.02× |
| No-op `just test`         |      1.05 s |  0.87 s |   1.21× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.97.1 check -p codex-tools --lib --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just clippy -p codex-tools --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just test -p codex-tools --lib --locked --offline \
  --no-tests fail tool_spec_name_covers_all_variants
```

Replace `+1.97.1` with `+ohm`, or set `RUSTUP_TOOLCHAIN=ohm`, to run the Ohm variants.

## Codex: codex-core

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.97.1 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     60.24 s |  62.94 s |   0.96× |
| Dependency edit, `check`  |      7.74 s |   0.52 s |  15.01× |
| Direct edit, `check`      |      1.90 s |   2.36 s |   0.80× |
| No-op `cargo check`       |      0.53 s |   0.42 s |   1.25× |
| Cold `just clippy`        |     94.78 s |  84.56 s |   1.12× |
| Dependency edit, `clippy` |     22.61 s |   0.64 s |  35.24× |
| Direct edit, `clippy`     |     10.93 s |   6.87 s |   1.59× |
| No-op `just clippy`       |      0.67 s |   0.55 s |   1.21× |
| Cold `just test`          |    118.16 s | 149.17 s |   0.79× |
| Dependency edit, `test`   |     22.28 s |   4.22 s |   5.28× |
| Direct edit, `test`       |     11.14 s |  14.85 s |   0.75× |
| No-op `just test`         |      1.19 s |   0.98 s |   1.21× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.97.1 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.97.1` with `+ohm`, or set `RUSTUP_TOOLCHAIN=ohm`, to run the Ohm variants.

## Reproducing the benchmarks

The benchmark runner requires [uv](https://docs.astral.sh/uv/), Git, and the upstream Rust and Ohm
toolchains. The Codex workflows also require [`just`](https://github.com/casey/just) and
`cargo-nextest`. Run it from the Ohm repository:

```console
uv run scripts/benchmark.py --dry-run
uv run scripts/benchmark.py
```

The runner clones the public repositories at exact benchmark-compatible source revisions:

- [uv `c22e6b71933443e9cd299d4b6ac8de035ed4825b`](https://github.com/astral-sh/uv/commit/c22e6b71933443e9cd299d4b6ac8de035ed4825b)
- [Codex `5157493c23713ac12034cf250ffb0a8ce0670277`](https://github.com/openai/codex/commit/5157493c23713ac12034cf250ffb0a8ce0670277)

Cloning requires network access, but the benchmark commands run offline, so Cargo dependencies must
already be cached. `--dry-run` prints the benchmark plan without cloning or running a build.

By default, the runner compares Rust 1.97.1 against `+ohm` across `uv` and `codex-core`, using eight
build jobs. Each workflow includes one cold build, three no-op runs, seven dependency edits, and five
direct edits. Use `--project` to run a smaller matrix:

```console
uv run scripts/benchmark.py \
  --project codex-core
```

Use `--uv-path` and `--codex-path` to reuse existing local repositories, or `--uv-rev` and
`--codex-rev` to override the pinned commits. Use `--upstream` and `--ohm` to select different
toolchains; `--jobs`, `--cold-runs`, `--noop-runs`, `--dependency-runs`, and `--direct-runs` to
control the sample counts; and `--output-dir` to choose a new or empty directory for the JSON results
and Markdown summary.

The runner creates temporary Git worktrees, isolates Cargo target directories by workflow and
toolchain, and applies reversible edits without modifying the original checkouts. Pass
`--require-idle` to wait for other Rust builds to finish and reject overlapping samples;
`--idle-timeout` controls the maximum wait, `--quiet-seconds` sets the required quiet window, and
`--contention-retries` controls how often an interrupted workflow restarts from a cold build. Pass
`--discard-targets` to remove each completed workflow's isolated build artifacts while preserving
its results and logs.
