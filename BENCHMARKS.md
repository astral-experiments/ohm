# Benchmarks

These benchmarks compare stock Rust 1.98.0 with `ohm-1.98.0-3` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
The main uv and Codex tables below come from one fresh Linux devbox study.
The earlier August 24 complete study and August 22 Linux uv study are retained in the historical
appendices.

The fresh Linux study finished on August 27, 2026 (UTC), on an AMD EPYC 9V74 devbox with 32 logical
CPUs and eight build jobs. Both toolchains use the same source revision, default development
profiles, and separate Cargo target directories. Dependencies are cached before timing begins.
The study started after six consecutive five-second CPU samples, each with at least 95% idle,
at most 0.5% I/O wait and 0.1% steal time, and no unrelated compiler processes. Samples
contaminated by concurrent builds are discarded. These are fresh paired comparisons against
stock Rust, not a matched comparison of Ohm revisions 2 and 3; the earlier study used different
hardware. The exact released toolchains were verified against the
[revision 3 manifest](toolchains/1.98.0/3.json).

- **Cold:** One build from an empty target directory.
- **Dependency (indirect) edit:** Median of seven implementation-only edits to a crate the target
  depends on. Its public API is unchanged, so Ohm can avoid rebuilding downstream crates.
- **Direct edit:** Median of five implementation-only edits to the target crate itself, which must
  be recompiled.
- **No-op:** Median of three runs without source changes.

Each test workflow builds and runs one existing test. The current uv workflow runs a black-box
integration test against the compiled `uv` executable; Codex runs a library test. The pinned Codex
revision uses Rust 1.95.0; these benchmarks use Rust 1.98.0 for both projects to match Ohm's Rust base.

The fresh Linux study completed all 216 planned samples: 192 successful core-workflow samples
and all 24 targeted build-to-check, formatting, and cross-worktree samples. All 216 passed
validation. None were discarded for interference.
The 216 samples include 100 uv samples and 116 Codex samples. Earlier studies are separate
historical evidence and are not pooled with these measurements. The benchmark runner and fixtures
are unchanged from [the release coordinator](https://github.com/astral-sh/ohm/commit/c7e962280a3419be3e07b592d6c897de6d575343).

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     66.81 s |  60.73 s |   1.10× |
| Dependency edit, `check`  |     10.25 s |   0.58 s |  17.80× |
| Direct edit, `check`      |      2.18 s |   1.94 s |   1.12× |
| No-op `cargo check`       |      0.57 s |   0.40 s |   1.42× |
| Cold `cargo clippy`       |     69.66 s |  60.56 s |   1.15× |
| Dependency edit, `clippy` |     14.69 s |   0.64 s |  22.91× |
| Direct edit, `clippy`     |      3.39 s |   3.01 s |   1.13× |
| No-op `cargo clippy`      |      0.60 s |   0.44 s |   1.36× |
| Cold `cargo test`         |    128.17 s | 117.48 s |   1.09× |
| Dependency edit, `test`   |     19.53 s |   4.08 s |   4.79× |
| Direct edit, `test`       |     17.09 s |  10.08 s |   1.70× |
| No-op `cargo test`        |      1.32 s |   1.14 s |   1.16× |

The measured commands are:

```console
cargo +1.98.0 check -p uv --lib --locked --offline
cargo +1.98.0 clippy -p uv --lib --locked --offline
cargo +1.98.0 test -p uv --test it --locked --offline help::help -- --exact
```

Replace `+1.98.0` with `+ohm-1.98.0-3` to run the Ohm variants.

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |    112.68 s |  96.13 s |   1.17× |
| Dependency edit, `check`  |     17.81 s |   1.00 s |  17.80× |
| Direct edit, `check`      |      4.47 s |   3.95 s |   1.13× |
| No-op `cargo check`       |      1.15 s |   0.81 s |   1.42× |
| Cold `just clippy`        |    170.81 s | 123.67 s |   1.38× |
| Dependency edit, `clippy` |     39.42 s |   1.18 s |  33.54× |
| Direct edit, `clippy`     |     19.23 s |  15.01 s |   1.28× |
| No-op `just clippy`       |      1.30 s |   0.94 s |   1.38× |
| Cold `just test`          |    224.82 s | 195.37 s |   1.15× |
| Dependency edit, `test`   |     43.76 s |   7.05 s |   6.21× |
| Direct edit, `test`       |     24.73 s |  22.03 s |   1.12× |
| No-op `just test`         |      2.49 s |   1.86 s |   1.34× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.98.0 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.98.0` with `+ohm-1.98.0-3`, or set `RUSTUP_TOOLCHAIN=ohm-1.98.0-3`,
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

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-3 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.80 s |      18.14 s |   3.52× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      6.89 s |       0.48 s |  14.26× |       1 |
| Codex   | Build, then check        | `codex-core`         |    104.55 s |      47.27 s |   2.21× |       1 |
| Codex   | No-op formatting         | Workspace            |     11.06 s |       0.32 s |  34.75× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     11.08 s |       0.52 s |  21.21× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.80 s |       0.61 s |   4.58× |       1 |

Together these workflows add 24 matched samples to the completed 192-sample core matrix, for a
full-study total of 216 successful samples.

## Reproducing the benchmarks

The benchmark runner requires [uv](https://docs.astral.sh/uv/), Git, and the upstream Rust and Ohm
toolchains. The Codex workflows also require [`just`](https://github.com/casey/just) and
`cargo-nextest`; this study used versions 1.58.0 and 0.9.140, respectively.
Run it from the Ohm repository:

```console
uv run scripts/benchmark.py --dry-run
uv run scripts/benchmark.py \
  --upstream 1.98.0 --ohm ohm-1.98.0-3 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
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

## Earlier Ohm 1.98.0-2 direct study — August 24, 2026

These measurements are preserved unchanged. This earlier study used an AMD EPYC-Milan Linux
devbox with 32 logical CPUs and eight build jobs, the same pinned uv and Codex source revisions,
and separate target directories. It completed 216 validated samples without interference:
192 core workflow samples and 24 feature samples. Dependency edits report seven-run medians,
direct edits five-run medians, and no-op runs three-run medians; cold builds and the other
feature workflows have one sample per compiler. These results are not pooled with the new study.

### uv

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |     91.65 s |      89.96 s |   1.02× |
| Dependency edit, `check`  |     15.84 s |       0.77 s |  20.59× |
| Direct edit, `check`      |      3.41 s |       2.97 s |   1.15× |
| No-op `cargo check`       |      0.70 s |       0.46 s |   1.52× |
| Cold `cargo clippy`       |     99.58 s |      91.21 s |   1.09× |
| Dependency edit, `clippy` |     20.62 s |       0.82 s |  25.11× |
| Direct edit, `clippy`     |      4.86 s |       4.30 s |   1.13× |
| No-op `cargo clippy`      |      0.73 s |       0.52 s |   1.39× |
| Cold `cargo test`         |    178.83 s |     176.08 s |   1.02× |
| Dependency edit, `test`   |     33.32 s |       6.07 s |   5.49× |
| Direct edit, `test`       |     24.57 s |      14.87 s |   1.65× |
| No-op `cargo test`        |      1.44 s |       1.20 s |   1.19× |

### Codex

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |    143.74 s |     136.28 s |   1.05× |
| Dependency edit, `check`  |     25.58 s |       1.14 s |  22.49× |
| Direct edit, `check`      |      6.25 s |       5.65 s |   1.11× |
| No-op `cargo check`       |      1.32 s |       0.97 s |   1.35× |
| Cold `just clippy`        |    222.87 s |     165.63 s |   1.35× |
| Dependency edit, `clippy` |     56.64 s |       1.36 s |  41.80× |
| Direct edit, `clippy`     |     28.11 s |      23.62 s |   1.19× |
| No-op `just clippy`       |      1.45 s |       1.46 s |   1.00× |
| Cold `just test`          |    293.08 s |     264.79 s |   1.11× |
| Dependency edit, `test`   |     67.59 s |       9.44 s |   7.16× |
| Direct edit, `test`       |     37.22 s |      31.46 s |   1.18× |
| No-op `just test`         |      4.34 s |       3.57 s |   1.22× |

### Additional feature workflows

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     81.49 s |      26.57 s |   3.07× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      9.36 s |       0.64 s |  14.55× |       1 |
| Codex   | Build, then check        | `codex-core`         |    132.83 s |      65.73 s |   2.02× |       1 |
| Codex   | No-op formatting         | Workspace            |     12.29 s |       0.31 s |  40.12× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     12.81 s |       0.46 s |  27.73× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      3.39 s |       0.73 s |   4.68× |       1 |

## Earlier Linux uv study — August 22, 2026

These earlier measurements are preserved unchanged; they are not part of the fresh 216-sample study.

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
