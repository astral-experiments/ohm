# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-11` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
A separate uv integration-test follow-up also reports `ohm-1.97.1-12` results on Linux.

Results were collected on an Apple M5 Max with 128 GB of memory and eight build jobs. Both toolchains
use the same source revision, default development profiles, and separate Cargo target directories.
Dependencies are cached before timing begins. Samples contaminated by concurrent builds are
discarded.

- **Cold:** One build from an empty target directory.
- **Dependency (indirect) edit:** Median of seven implementation-only edits to a crate the target
  depends on. Its public API is unchanged, so Ohm can avoid rebuilding downstream crates.
- **Direct edit:** Median of five implementation-only edits to the target crate itself, which must
  be recompiled.
- **No-op:** Median of three runs without source changes.

Each test workflow builds and runs one existing test. The current uv workflow runs a black-box
integration test against the compiled `uv` executable; Codex runs a library test. Codex normally
pins Rust 1.95.0; these benchmarks use Rust 1.97.1 for both projects to match Ohm's Rust base.

The tables below come from a complete 192-sample study of these existing workflows. The benchmark
runner now also collects 24 targeted samples for build-to-check reuse, incremental formatting, and
cross-worktree artifact sharing; those additional workflows are described below and are not included
in the historical results.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The historical `test` rows in this table used the previous library-test workflow; the
current integration-test workflow is measured separately below.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     41.72 s | 42.13 s |   0.99× |
| Dependency edit, `check`  |      4.50 s |  0.47 s |   9.49× |
| Direct edit, `check`      |      0.94 s |  1.02 s |   0.93× |
| No-op `cargo check`       |      0.29 s |  0.38 s |   0.76× |
| Cold `cargo clippy`       |     42.34 s | 41.72 s |   1.01× |
| Dependency edit, `clippy` |      8.82 s |  0.53 s |  16.68× |
| Direct edit, `clippy`     |      2.08 s |  1.49 s |   1.40× |
| No-op `cargo clippy`      |      0.33 s |  0.42 s |   0.78× |
| Cold `cargo test`         |     65.01 s | 66.29 s |   0.98× |
| Dependency edit, `test`   |     10.56 s |  1.71 s |   6.18× |
| Direct edit, `test`       |      7.12 s |  3.24 s |   2.20× |
| No-op `cargo test`        |      0.34 s |  0.29 s |   1.16× |

The measured commands are:

```console
cargo +1.97.1 check -p uv --lib --locked --offline
cargo +1.97.1 clippy -p uv --lib --locked --offline
cargo +1.97.1 test -p uv --test it --locked --offline help::help -- --exact
```

Replace `+1.97.1` with `+ohm` to run the Ohm variants.

### uv integration tests

The current uv test workflow selects the existing `help::help` integration test, which executes the
real `uv` CLI. Changing `crates/uv/src/install_source.rs` still recompiles the application and
relinks its executable, while Ohm can reuse the integration-test executable because it does not use
the package library. Changing `uv-normalize` retains the existing dependency-edit workload.

The following separate 32-sample comparison used Rust 1.97.1 and `ohm-1.97.1-12` on a Linux AMD
EPYC 7763 machine with eight build jobs. Both toolchains used the same pinned uv revision, the same
integration test, offline dependencies, isolated target directories, and uncontaminated samples.

| Phase           | Rust 1.97.1 | Ohm 1.97.1-12 | Speedup | Samples |
| --------------- | ----------: | ------------: | ------: | ------: |
| Cold            |    119.06 s |      144.88 s |   0.82× |       1 |
| No-op           |      1.21 s |        1.07 s |   1.13× |       3 |
| Dependency edit |     19.78 s |        4.05 s |   4.88× |       7 |
| Direct edit     |     16.03 s |       11.40 s |   1.41× |       5 |

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.97.1 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     64.73 s |  68.17 s |   0.95× |
| Dependency edit, `check`  |      7.83 s |   0.87 s |   9.02× |
| Direct edit, `check`      |      1.93 s |   2.09 s |   0.92× |
| No-op `cargo check`       |      0.57 s |   0.79 s |   0.72× |
| Cold `just clippy`        |     97.34 s |  89.41 s |   1.09× |
| Dependency edit, `clippy` |     23.44 s |   1.06 s |  22.11× |
| Direct edit, `clippy`     |     12.18 s |   8.31 s |   1.47× |
| No-op `just clippy`       |      0.65 s |   0.89 s |   0.72× |
| Cold `just test`          |    128.57 s | 129.83 s |   0.99× |
| Dependency edit, `test`   |     26.44 s |   6.21 s |   4.26× |
| Direct edit, `test`       |     15.10 s |  13.08 s |   1.15× |
| No-op `just test`         |      1.33 s |   1.10 s |   1.21× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.97.1 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.97.1` with `+ohm`, or set `RUSTUP_TOOLCHAIN=ohm`, to run the Ohm variants.

## Additional feature workflows

The benchmark runner includes three additional workflows that exercise optimizations not covered by
the existing check, Clippy, and test matrix:

- **Build-to-check reuse:** Build `uv` or `codex-core` without timing, then measure the first
  `cargo check` against the same target directory. This measures whether already-built registry
  dependencies can be reused across commands.
- **Incremental formatting:** Run Codex's actual
  `cargo fmt -- --config imports_granularity=Item --check` command. After an untimed warmup, measure
  three unchanged runs and five reversible, correctly formatted source edits. Ohm must publish a
  real incremental-formatting snapshot before its results are accepted.
- **Shared-worktree builds:** Build `uv` or `codex-core` in one checkout, then measure a build with a
  real workspace edit in a second checkout at the same revision. Both toolchains receive the same
  explicit `CARGO_BUILD_BUILD_DIR`, separate checkout-private target directories, and a trusted
  system-native-tool `PATH`. Unverified user-installed native-tool wrappers disable sharing; Ohm
  must publish its shared-cache marker and immutable registry artifacts before its results are
  accepted.

Together these workflows add 24 matched samples to the original 192-sample matrix, for a default
total of 216 samples. The generated JSON results and Markdown summary report their measurements
separately from the historical workflows.

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
build jobs. Each original workflow includes one cold build, three no-op runs, seven dependency edits,
and five direct edits; the three additional feature workflows run afterward. Use `--project` to run a
smaller matrix:

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
