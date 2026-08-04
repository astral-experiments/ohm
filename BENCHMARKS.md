# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-1` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.

Results were collected on an Apple M5 Max with 128 GB of memory and eight build jobs. Both toolchains
use the same source revision, default development profiles, and separate Cargo target directories.
Dependencies are cached before timing begins.

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
| Cold `cargo check`        |     36.12 s | 40.22 s |   0.90× |
| Dependency edit, `check`  |      4.47 s |  0.43 s |  10.38× |
| Direct edit, `check`      |      0.94 s |  1.19 s |   0.79× |
| No-op `cargo check`       |      0.32 s |  0.32 s |   1.00× |
| Cold `cargo clippy`       |     38.66 s | 39.01 s |   0.99× |
| Dependency edit, `clippy` |      8.58 s |  0.44 s |  19.66× |
| Direct edit, `clippy`     |      2.00 s |  1.73 s |   1.16× |
| No-op `cargo clippy`      |      0.33 s |  0.38 s |   0.88× |
| Cold `cargo test`         |     61.06 s | 72.29 s |   0.84× |
| Dependency edit, `test`   |      9.15 s |  1.13 s |   8.10× |
| Direct edit, `test`       |      2.72 s |  3.25 s |   0.84× |
| No-op `cargo test`        |      0.32 s |  0.32 s |   1.02× |

The measured commands are:

```console
cargo +1.97.1 check -p uv --lib --locked --offline
cargo +1.97.1 clippy -p uv --lib --locked --offline
cargo +1.97.1 test -p uv --lib --locked --offline \
  install_source::tests::detects_homebrew_cellar -- --exact
```

Replace `+1.97.1` with `+ohm` to run the Ohm variants.

## Codex

These benchmarks target the `codex-tools` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-tools` itself.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     42.00 s | 46.98 s |   0.89× |
| Dependency edit, `check`  |      4.68 s |  0.61 s |   7.70× |
| Direct edit, `check`      |      0.74 s |  0.75 s |   0.99× |
| No-op `cargo check`       |      0.50 s |  0.54 s |   0.92× |
| Cold `just clippy`        |     46.06 s | 45.17 s |   1.02× |
| Dependency edit, `clippy` |      8.33 s |  0.68 s |  12.19× |
| Direct edit, `clippy`     |      1.08 s |  0.94 s |   1.15× |
| No-op `just clippy`       |      0.59 s |  0.60 s |   0.99× |
| Cold `just test`          |     57.42 s | 67.51 s |   0.85× |
| Dependency edit, `test`   |      8.30 s |  1.97 s |   4.22× |
| Direct edit, `test`       |      2.40 s |  2.62 s |   0.91× |
| No-op `just test`         |      1.10 s |  1.18 s |   0.93× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.97.1 check -p codex-tools --lib --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just clippy -p codex-tools --locked --offline
RUSTUP_TOOLCHAIN=1.97.1 just test -p codex-tools --lib --locked --offline \
  --no-tests fail tool_spec_name_covers_all_variants
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
