# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-9` across the
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
| Cold `cargo check`        |     39.76 s | 38.77 s |   1.03× |
| Dependency edit, `check`  |      4.31 s |  0.29 s |  14.85× |
| Direct edit, `check`      |      0.88 s |  0.80 s |   1.10× |
| No-op `cargo check`       |      0.29 s |  0.24 s |   1.22× |
| Cold `cargo clippy`       |     41.21 s | 37.66 s |   1.09× |
| Dependency edit, `clippy` |      8.42 s |  0.32 s |  26.07× |
| Direct edit, `clippy`     |      1.99 s |  1.25 s |   1.59× |
| No-op `cargo clippy`      |      0.29 s |  0.24 s |   1.23× |
| Cold `cargo test`         |     64.42 s | 64.22 s |   1.00× |
| Dependency edit, `test`   |      9.25 s |  1.30 s |   7.14× |
| Direct edit, `test`       |      3.18 s |  2.60 s |   1.22× |
| No-op `cargo test`        |      0.31 s |  0.23 s |   1.34× |

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
| Cold `cargo check`        |     61.65 s |  61.65 s |   1.00× |
| Dependency edit, `check`  |      7.36 s |   0.51 s |  14.32× |
| Direct edit, `check`      |      1.84 s |   1.67 s |   1.10× |
| No-op `cargo check`       |      0.57 s |   0.43 s |   1.32× |
| Cold `just clippy`        |     93.64 s |  85.15 s |   1.10× |
| Dependency edit, `clippy` |     22.28 s |   0.61 s |  36.28× |
| Direct edit, `clippy`     |     11.45 s |   7.43 s |   1.54× |
| No-op `just clippy`       |      0.62 s |   0.50 s |   1.23× |
| Cold `just test`          |    122.22 s | 128.03 s |   0.95× |
| Dependency edit, `test`   |     24.71 s |   5.62 s |   4.40× |
| Direct edit, `test`       |     13.16 s |  11.37 s |   1.16× |
| No-op `just test`         |      1.19 s |   1.02 s |   1.17× |

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
