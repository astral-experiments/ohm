# Benchmarks

These benchmarks compare stock Rust 1.98.0 with `ohm-1.98.0-1` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
A separate complete uv comparison also measures the released toolchain on Linux.

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
pins Rust 1.95.0; these benchmarks use Rust 1.98.0 for both projects to match Ohm's Rust base.

The Rust 1.98.0 study completed all 216 planned samples: 192 successful core-workflow samples and
all 24 targeted build-to-check, formatting, and cross-worktree samples. This includes all 32 Codex
Clippy samples, which could not be collected with Ohm 1.97.1-20 because its parallel frontend
overflowed the query-depth limit. The Rust 1.98 release preserves the parallel frontend and fixes
the overflow. An additional 100 uncontaminated Linux uv samples cover every check, Clippy, test,
build-to-check, and cross-worktree workflow.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     65.65 s |  60.36 s |   1.09× |
| Dependency edit, `check`  |      7.91 s |   0.61 s |  12.87× |
| Direct edit, `check`      |      1.50 s |   1.41 s |   1.06× |
| No-op `cargo check`       |      1.39 s |   0.31 s |   4.46× |
| Cold `cargo clippy`       |     74.52 s |  63.25 s |   1.18× |
| Dependency edit, `clippy` |     10.45 s |   0.51 s |  20.58× |
| Direct edit, `clippy`     |      1.79 s |   1.83 s |   0.98× |
| No-op `cargo clippy`      |      0.32 s |   0.29 s |   1.12× |
| Cold `cargo test`         |    123.45 s | 113.87 s |   1.08× |
| Dependency edit, `test`   |     14.26 s |   2.16 s |   6.60× |
| Direct edit, `test`       |     11.70 s |   5.06 s |   2.31× |
| No-op `cargo test`        |      0.95 s |   0.88 s |   1.08× |

The measured commands are:

```console
cargo +1.98.0 check -p uv --lib --locked --offline
cargo +1.98.0 clippy -p uv --lib --locked --offline
cargo +1.98.0 test -p uv --test it --locked --offline help::help -- --exact
```

Replace `+1.98.0` with `+ohm-1.98.0-1` to run the Ohm variants.

### uv on Linux

The complete 100-sample Linux comparison used Rust 1.98.0 and `ohm-1.98.0-1` on an AMD EPYC-Milan
machine with eight build jobs. Both toolchains used the same pinned uv revision, offline
dependencies, isolated target directories, and uncontaminated samples.

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-1 | Speedup | Samples |
| ------------------------- | ----------: | -----------: | ------: | ------: |
| Cold `cargo check`        |     85.20 s |      78.46 s |   1.09× |       1 |
| No-op `cargo check`       |      0.63 s |       0.47 s |   1.36× |       3 |
| Dependency edit, `check`  |     13.53 s |       0.74 s |  18.19× |       7 |
| Direct edit, `check`      |      2.84 s |       2.69 s |   1.06× |       5 |
| Cold `cargo clippy`       |     91.06 s |      81.55 s |   1.12× |       1 |
| No-op `cargo clippy`      |      0.76 s |       0.63 s |   1.21× |       3 |
| Dependency edit, `clippy` |     19.67 s |       0.83 s |  23.62× |       7 |
| Direct edit, `clippy`     |      4.59 s |       4.45 s |   1.03× |       5 |
| Build, then check         |     82.93 s |      27.39 s |   3.03× |       1 |
| Shared-worktree build     |     11.78 s |       0.88 s |  13.42× |       1 |

The uv integration-test workflow selects the existing `help::help` integration test, which executes
the real `uv` CLI. Changing `crates/uv/src/install_source.rs` still recompiles the application and
relinks its executable, while Ohm can reuse the integration-test executable because it does not use
the package library. Changing `uv-normalize` retains the existing dependency-edit workload.

These 32 integration-test samples are included in the complete 100-sample Linux comparison:

| Phase           | Rust 1.98.0 | Ohm 1.98.0-1 | Speedup | Samples |
| --------------- | ----------: | -----------: | ------: | ------: |
| Cold            |    162.01 s |     161.71 s |   1.00× |       1 |
| No-op           |      1.91 s |       1.72 s |   1.11× |       3 |
| Dependency edit |     31.13 s |       6.09 s |   5.11× |       7 |
| Direct edit     |     25.89 s |      16.58 s |   1.56× |       5 |

The previous Rust 1.97.1 comparison is preserved as historical evidence:

| Phase           | Rust 1.97.1 | Ohm 1.97.1-20 | Speedup | Samples |
| --------------- | ----------: | ------------: | ------: | ------: |
| Cold            |    157.47 s |      164.23 s |   0.96× |       1 |
| No-op           |      1.96 s |        1.89 s |   1.04× |       3 |
| Dependency edit |     31.17 s |        5.31 s |   5.88× |       7 |
| Direct edit     |     23.33 s |       18.06 s |   1.29× |       5 |

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

> **Previous release regression resolved:** At pinned Codex revision `5157493c23713ac12034cf250ffb0a8ce0670277`, Ohm 1.97.1-20 reproducibly failed `just clippy -p codex-core --locked --offline` with `queries overflow the depth limit!`. Ohm 1.98.0-1 completes the same command with the parallel frontend enabled and passes all 32 previously unavailable Clippy samples.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |    105.30 s |  93.16 s |   1.13× |
| Dependency edit, `check`  |     11.21 s |   0.68 s |  16.38× |
| Direct edit, `check`      |      2.19 s |   1.96 s |   1.12× |
| No-op `cargo check`       |      1.18 s |   0.81 s |   1.46× |
| Cold `just clippy`        |    111.64 s |  99.64 s |   1.12× |
| Dependency edit, `clippy` |     22.19 s |   0.75 s |  29.66× |
| Direct edit, `clippy`     |      9.86 s |   7.64 s |   1.29× |
| No-op `just clippy`       |      0.72 s |   0.58 s |   1.24× |
| Cold `just test`          |    170.33 s | 163.49 s |   1.04× |
| Dependency edit, `test`   |     25.30 s |   3.27 s |   7.73× |
| Direct edit, `test`       |     12.58 s |   9.96 s |   1.26× |
| No-op `just test`         |      1.28 s |   1.05 s |   1.22× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.98.0 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.98.0` with `+ohm-1.98.0-1`, or set `RUSTUP_TOOLCHAIN=ohm-1.98.0-1`,
to run the Ohm variants.

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
eight build jobs as the 192 completed core samples.

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-1 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     43.91 s |      10.69 s |   4.11× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      3.92 s |       0.30 s |  12.97× |       1 |
| Codex   | Build, then check        | `codex-core`         |     70.43 s |      28.08 s |   2.51× |       1 |
| Codex   | No-op formatting         | Workspace            |      5.23 s |       0.16 s |  33.30× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |      5.48 s |       0.68 s |   8.08× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      1.72 s |       0.52 s |   3.33× |       1 |

Together these workflows add 24 matched samples to the completed 192-sample core matrix, for a
full-study total of 216 successful samples.

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

By default, the runner compares Rust 1.98.0 against `+ohm` across `uv` and `codex-core`, using eight
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
