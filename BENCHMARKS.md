# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-7` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.

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

Each test workflow builds and runs one existing unit test. Codex normally pins Rust 1.95.0; these
benchmarks use Rust 1.97.1 for both projects to match Ohm's Rust base.

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself.

| Workflow                  | Rust 1.97.1 |     Ohm | Speedup |
| ------------------------- | ----------: | ------: | ------: |
| Cold `cargo check`        |     40.89 s | 42.29 s |   0.97× |
| Dependency edit, `check`  |      4.84 s |  0.34 s |  14.18× |
| Direct edit, `check`      |      1.00 s |  0.95 s |   1.06× |
| No-op `cargo check`       |      0.31 s |  0.24 s |   1.29× |
| Cold `cargo clippy`       |     47.03 s | 45.86 s |   1.03× |
| Dependency edit, `clippy` |      9.61 s |  0.39 s |  24.95× |
| Direct edit, `clippy`     |      2.28 s |  1.56 s |   1.46× |
| No-op `cargo clippy`      |      0.33 s |  0.27 s |   1.22× |
| Cold `cargo test`         |     64.88 s | 74.47 s |   0.87× |
| Dependency edit, `test`   |     10.01 s |  1.77 s |   5.65× |
| Direct edit, `test`       |      3.46 s |  3.70 s |   0.93× |
| No-op `cargo test`        |      0.30 s |  0.25 s |   1.22× |

The measured commands are:

```console
cargo +1.97.1 check -p uv --lib --locked --offline
cargo +1.97.1 clippy -p uv --lib --locked --offline
cargo +1.97.1 test -p uv --lib --locked --offline \
  install_source::tests::detects_homebrew_cellar -- --exact
```

Replace `+1.97.1` with `+ohm` to run the Ohm variants.

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.97.1 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     67.25 s |  65.71 s |   1.02× |
| Dependency edit, `check`  |      8.40 s |   0.65 s |  12.88× |
| Direct edit, `check`      |      2.10 s |   1.87 s |   1.12× |
| No-op `cargo check`       |      0.59 s |   0.47 s |   1.26× |
| Cold `just clippy`        |    103.62 s |  91.26 s |   1.14× |
| Dependency edit, `clippy` |     23.19 s |   0.68 s |  34.03× |
| Direct edit, `clippy`     |     11.32 s |   6.81 s |   1.66× |
| No-op `just clippy`       |      0.66 s |   0.56 s |   1.18× |
| Cold `just test`          |    132.52 s | 170.74 s |   0.78× |
| Dependency edit, `test`   |     25.14 s |   8.67 s |   2.90× |
| Direct edit, `test`       |     14.21 s |  18.25 s |   0.78× |
| No-op `just test`         |      1.29 s |   1.08 s |   1.20× |

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
