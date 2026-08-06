# Benchmarks

These benchmarks compare stock Rust 1.97.1 with `ohm-1.97.1-8` across the
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
| Cold `cargo check`        |     41.88 s | 41.22 s |   1.02× |
| Dependency edit, `check`  |      4.53 s |  0.32 s |  14.10× |
| Direct edit, `check`      |      1.04 s |  0.95 s |   1.09× |
| No-op `cargo check`       |      0.29 s |  0.24 s |   1.18× |
| Cold `cargo clippy`       |     43.77 s | 43.36 s |   1.01× |
| Dependency edit, `clippy` |      8.47 s |  0.36 s |  23.74× |
| Direct edit, `clippy`     |      1.97 s |  1.28 s |   1.53× |
| No-op `cargo clippy`      |      0.33 s |  0.29 s |   1.16× |
| Cold `cargo test`         |     63.55 s | 65.17 s |   0.98× |
| Dependency edit, `test`   |      9.70 s |  1.65 s |   5.89× |
| Direct edit, `test`       |      3.40 s |  3.27 s |   1.04× |
| No-op `cargo test`        |      0.30 s |  0.24 s |   1.23× |

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
| Cold `cargo check`        |     64.27 s |  67.84 s |   0.95× |
| Dependency edit, `check`  |      7.70 s |   0.54 s |  14.30× |
| Direct edit, `check`      |      1.90 s |   1.71 s |   1.11× |
| No-op `cargo check`       |      0.58 s |   0.45 s |   1.29× |
| Cold `just clippy`        |    107.56 s |  90.36 s |   1.19× |
| Dependency edit, `clippy` |     23.07 s |   0.68 s |  34.07× |
| Direct edit, `clippy`     |     11.12 s |   6.69 s |   1.66× |
| No-op `just clippy`       |      0.70 s |   0.57 s |   1.23× |
| Cold `just test`          |    127.23 s | 130.74 s |   0.97× |
| Dependency edit, `test`   |     29.73 s |   6.91 s |   4.30× |
| Direct edit, `test`       |     14.89 s |  14.05 s |   1.06× |
| No-op `just test`         |      1.30 s |   1.09 s |   1.20× |

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
