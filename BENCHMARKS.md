# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-19` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
A separate 32-sample uv integration-test comparison also measures the same release on Linux.

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

The tables below come from one complete 216-sample study: 192 samples cover these existing
workflows, and 24 targeted samples measure build-to-check reuse, incremental formatting, and
cross-worktree artifact sharing.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     38.38 s | 38.66 s |   0.99× |
| Dependency edit, `check`  |      4.59 s |  0.31 s |  14.60× |
| Direct edit, `check`      |      0.99 s |  0.83 s |   1.20× |
| No-op `cargo check`       |      0.28 s |  0.23 s |   1.21× |
| Cold `cargo clippy`       |     40.54 s | 37.29 s |   1.09× |
| Dependency edit, `clippy` |      8.89 s |  0.37 s |  23.97× |
| Direct edit, `clippy`     |      2.13 s |  1.26 s |   1.69× |
| No-op `cargo clippy`      |      0.32 s |  0.27 s |   1.17× |
| Cold `cargo test`         |     66.54 s | 62.02 s |   1.07× |
| Dependency edit, `test`   |     10.99 s |  1.88 s |   5.83× |
| Direct edit, `test`       |      6.58 s |  3.89 s |   1.69× |
| No-op `cargo test`        |      0.92 s |  0.86 s |   1.07× |

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

The following separate 32-sample comparison used Rust 1.97.1 and `ohm-1.97.1-19` on a Linux AMD EPYC-Milan machine with eight build jobs. Both toolchains used the same pinned uv revision, the same
integration test, offline dependencies, isolated target directories, and uncontaminated samples.

| Phase           | Rust 1.97.1 | Ohm 1.97.1-19 | Speedup | Samples |
| --------------- | ----------: | ------------: | ------: | ------: |
| Cold            |    149.70 s |      168.13 s |   0.89× |       1 |
| No-op           |      1.60 s |        1.31 s |   1.22× |       3 |
| Dependency edit |     31.92 s |        5.56 s |   5.74× |       7 |
| Direct edit     |     21.66 s |       14.58 s |   1.49× |       5 |

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.97.1 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     61.38 s |  59.19 s |   1.04× |
| Dependency edit, `check`  |      7.63 s |   0.51 s |  14.83× |
| Direct edit, `check`      |      1.88 s |   1.57 s |   1.20× |
| No-op `cargo check`       |      0.51 s |   0.41 s |   1.25× |
| Cold `just clippy`        |     93.10 s |  75.90 s |   1.23× |
| Dependency edit, `clippy` |     23.80 s |   0.70 s |  33.91× |
| Direct edit, `clippy`     |     10.91 s |   6.05 s |   1.80× |
| No-op `just clippy`       |      0.65 s |   0.54 s |   1.21× |
| Cold `just test`          |    117.61 s | 112.69 s |   1.04× |
| Dependency edit, `test`   |     21.92 s |   2.97 s |   7.38× |
| Direct edit, `test`       |     10.79 s |   9.14 s |   1.18× |
| No-op `just test`         |      1.18 s |   0.97 s |   1.21× |

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
- **Shared-worktree builds:** Build a real workspace dependency (`uv-normalize` or
  `codex-utils-string`) in one checkout, then measure a build with a real edit to that dependency in
  a second checkout at the same revision. Stock Rust uses separate build directories for each
  checkout; Ohm shares one build directory while keeping workspace outputs private. This gives both
  toolchains equivalent workspace isolation while allowing Ohm to reuse immutable registry
  artifacts. Both receive separate target directories and the same trusted system-native-tool
  `PATH`. Ohm must publish its shared-cache marker and immutable registry artifacts before its
  results are accepted.

All 24 feature samples were collected with the same released toolchains, pinned repositories, and
eight build jobs as the 192 core samples in one complete, uncontaminated study.

| Project | Workflow                 | Package              | Rust 1.97.1 | Ohm 1.97.1-19 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | ------------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     34.33 s |       13.72 s |   2.50× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      3.39 s |        0.30 s |  11.34× |       1 |
| Codex   | Build, then check        | `codex-core`         |     56.69 s |       30.88 s |   1.84× |       1 |
| Codex   | No-op formatting         | Workspace            |      4.50 s |        0.14 s |  31.88× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |      4.46 s |        0.21 s |  21.25× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      1.42 s |        0.31 s |   4.60× |       1 |

Together these workflows add 24 matched samples to the original 192-sample matrix, for a default
total of 216 samples. The generated JSON results and Markdown summary distinguish the individual
workflows within the same complete study.

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
