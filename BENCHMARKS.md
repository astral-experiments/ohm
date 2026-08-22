# Benchmarks

These benchmarks compare stock Rust 1.98.0 with `ohm-1.98.0-2` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
A separate complete uv comparison also measures the released toolchain on Linux.

Results were collected on August 22, 2026 (UTC), on an Apple M5 Max with 128 GB of memory and eight build
jobs. Both toolchains use the same source revision, default development profiles, and separate
Cargo target directories.
Dependencies are cached before timing begins. Samples contaminated by concurrent builds are
discarded. The local study started after a 30-second window with at least 90% CPU idle and no
unrelated compiler processes. These are fresh paired comparisons against stock Rust, not a matched
comparison of Ohm revisions 1 and 2.

- **Cold:** One build from an empty target directory.
- **Dependency (indirect) edit:** Median of seven implementation-only edits to a crate the target
  depends on. Its public API is unchanged, so Ohm can avoid rebuilding downstream crates.
- **Direct edit:** Median of five implementation-only edits to the target crate itself, which must
  be recompiled.
- **No-op:** Median of three runs without source changes.

Each test workflow builds and runs one existing test. The current uv workflow runs a black-box
integration test against the compiled `uv` executable; Codex runs a library test. The pinned Codex
revision uses Rust 1.95.0; these benchmarks use Rust 1.98.0 for both projects to match Ohm's Rust base.

The Ohm 1.98.0 revision 2 study completed all 216 planned samples: 192 successful core-workflow
samples and all 24 targeted build-to-check, formatting, and cross-worktree samples. An additional 100
uncontaminated Linux uv samples cover every check, Clippy, test, build-to-check, and cross-worktree
workflow. All 316 direct-workflow samples passed validation; none were discarded for interference.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.98.0 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     37.85 s | 36.45 s |   1.04× |
| Dependency edit, `check`  |      4.77 s |  0.55 s |   8.73× |
| Direct edit, `check`      |      1.15 s |  1.04 s |   1.10× |
| No-op `cargo check`       |      0.46 s |  0.42 s |   1.09× |
| Cold `cargo clippy`       |     39.15 s | 37.27 s |   1.05× |
| Dependency edit, `clippy` |      6.85 s |  0.88 s |   7.79× |
| Direct edit, `clippy`     |      1.78 s |  1.72 s |   1.03× |
| No-op `cargo clippy`      |      0.74 s |  0.71 s |   1.04× |
| Cold `cargo test`         |     64.91 s | 61.06 s |   1.06× |
| Dependency edit, `test`   |     10.48 s |  2.16 s |   4.84× |
| Direct edit, `test`       |      7.53 s |  3.98 s |   1.89× |
| No-op `cargo test`        |      1.31 s |  1.26 s |   1.04× |

The measured commands are:

```console
cargo +1.98.0 check -p uv --lib --locked --offline
cargo +1.98.0 clippy -p uv --lib --locked --offline
cargo +1.98.0 test -p uv --test it --locked --offline help::help -- --exact
```

Replace `+1.98.0` with `+ohm-1.98.0-2` to run the Ohm variants.

### uv on Linux

The complete 100-sample Linux comparison used Rust 1.98.0 and `ohm-1.98.0-2` on an AMD EPYC-Milan
machine with 32 logical CPUs and eight build jobs. Both toolchains used the same pinned uv revision,
offline dependencies, isolated target directories, and uncontaminated samples.

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| ------------------------- | ----------: | -----------: | ------: | ------: |
| Cold `cargo check`        |     84.99 s |      74.84 s |   1.14× |       1 |
| No-op `cargo check`       |      0.64 s |       0.44 s |   1.47× |       3 |
| Dependency edit, `check`  |     13.74 s |       0.70 s |  19.71× |       7 |
| Direct edit, `check`      |      2.92 s |       2.69 s |   1.09× |       5 |
| Cold `cargo clippy`       |     85.51 s |      76.78 s |   1.11× |       1 |
| No-op `cargo clippy`      |      0.69 s |       0.48 s |   1.43× |       3 |
| Dependency edit, `clippy` |     19.40 s |       0.76 s |  25.39× |       7 |
| Direct edit, `clippy`     |      4.58 s |       4.07 s |   1.12× |       5 |
| Build, then check         |     83.06 s |      25.67 s |   3.24× |       1 |
| Shared-worktree build     |     10.34 s |       0.83 s |  12.48× |       1 |

The uv integration-test workflow selects the existing `help::help` integration test, which executes
the real `uv` CLI. Changing `crates/uv/src/install_source.rs` still recompiles the application and
relinks its executable, while Ohm can reuse the integration-test executable because it does not use
the package library. Changing `uv-normalize` retains the existing dependency-edit workload.

These 32 integration-test samples are included in the complete 100-sample Linux comparison:

| Phase           | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| --------------- | ----------: | -----------: | ------: | ------: |
| Cold            |    159.07 s |     164.29 s |   0.97× |       1 |
| No-op           |      2.02 s |       1.34 s |   1.51× |       3 |
| Dependency edit |     31.94 s |       5.88 s |   5.43× |       7 |
| Direct edit     |     26.82 s |      18.12 s |   1.48× |       5 |

The single cold integration-test build was 3.3% slower with Ohm; unchanged runs and both edit
workflows were faster. The cold result is retained rather than excluded from the comparison.

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

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     61.54 s |  52.83 s |   1.16× |
| Dependency edit, `check`  |      8.58 s |   0.86 s |  10.00× |
| Direct edit, `check`      |      2.19 s |   1.96 s |   1.12× |
| No-op `cargo check`       |      0.72 s |   0.60 s |   1.21× |
| Cold `just clippy`        |     92.69 s |  68.64 s |   1.35× |
| Dependency edit, `clippy` |     18.64 s |   1.17 s |  15.99× |
| Direct edit, `clippy`     |      8.74 s |   6.57 s |   1.33× |
| No-op `just clippy`       |      1.12 s |   1.02 s |   1.10× |
| Cold `just test`          |    124.13 s | 106.47 s |   1.17× |
| Dependency edit, `test`   |     23.68 s |   4.58 s |   5.17× |
| Direct edit, `test`       |     12.01 s |  10.10 s |   1.19× |
| No-op `just test`         |      3.09 s |   2.95 s |   1.05× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.98.0 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.98.0` with `+ohm-1.98.0-2`, or set `RUSTUP_TOOLCHAIN=ohm-1.98.0-2`,
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

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     35.33 s |       9.73 s |   3.63× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      3.64 s |       0.53 s |   6.87× |       1 |
| Codex   | Build, then check        | `codex-core`         |     56.32 s |      22.29 s |   2.53× |       1 |
| Codex   | No-op formatting         | Workspace            |      4.64 s |       0.57 s |   8.17× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |      4.65 s |       0.66 s |   7.01× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      1.54 s |       0.51 s |   3.03× |       1 |

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
