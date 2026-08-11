# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-12` across the
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

The tables below come from one complete 216-sample study: 192 samples cover these existing
workflows, and 24 targeted samples measure build-to-check reuse, incremental formatting, and
cross-worktree artifact sharing.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     40.26 s | 41.07 s |   0.98× |
| Dependency edit, `check`  |      4.51 s |  0.32 s |  14.15× |
| Direct edit, `check`      |      0.95 s |  0.87 s |   1.10× |
| No-op `cargo check`       |      0.31 s |  0.24 s |   1.30× |
| Cold `cargo clippy`       |     44.96 s | 43.40 s |   1.04× |
| Dependency edit, `clippy` |      8.99 s |  0.37 s |  24.16× |
| Direct edit, `clippy`     |      2.07 s |  1.32 s |   1.57× |
| No-op `cargo clippy`      |      0.35 s |  0.29 s |   1.19× |
| Cold `cargo test`         |     70.36 s | 71.39 s |   0.99× |
| Dependency edit, `test`   |     13.28 s |  3.97 s |   3.35× |
| Direct edit, `test`       |      8.49 s |  5.87 s |   1.45× |
| No-op `cargo test`        |      2.29 s |  2.25 s |   1.02× |

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
| Cold `cargo check`        |     65.55 s |  68.89 s |   0.95× |
| Dependency edit, `check`  |      7.93 s |   0.57 s |  14.03× |
| Direct edit, `check`      |      2.10 s |   2.07 s |   1.02× |
| No-op `cargo check`       |      0.58 s |   0.46 s |   1.26× |
| Cold `just clippy`        |    107.45 s |  90.30 s |   1.19× |
| Dependency edit, `clippy` |     23.57 s |   0.73 s |  32.07× |
| Direct edit, `clippy`     |     11.67 s |   7.36 s |   1.58× |
| No-op `just clippy`       |      0.69 s |   0.57 s |   1.21× |
| Cold `just test`          |    138.16 s | 142.49 s |   0.97× |
| Dependency edit, `test`   |     26.35 s |   6.41 s |   4.11× |
| Direct edit, `test`       |     14.43 s |  12.12 s |   1.19× |
| No-op `just test`         |      1.51 s |   1.13 s |   1.34× |

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
  `PATH`. Unverified user-installed native-tool wrappers disable sharing; Ohm must publish its
  shared-cache marker and immutable registry artifacts before its results are accepted.

All 24 feature samples were collected with the same released toolchains, pinned repositories, and
eight build jobs as the 192 core samples in one complete, uncontaminated study.

| Project | Workflow                 | Package              | Rust 1.97.1 | Ohm 1.97.1-12 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | ------------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     36.45 s |       17.14 s |   2.13× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      4.01 s |        2.97 s |   1.35× |       1 |
| Codex   | Build, then check        | `codex-core`         |     60.93 s |       37.14 s |   1.64× |       1 |
| Codex   | No-op formatting         | Workspace            |      5.04 s |        0.89 s |   5.67× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |      5.12 s |        3.11 s |   1.65× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      1.62 s |        0.32 s |   5.01× |       1 |

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
