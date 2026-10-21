# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

With Ohm, incremental builds can be up to 29× faster, replayed development sessions take around
41% less time, and `target/` disk usage decreases by around 55%.

Comparing stock Rust and Ohm on replayed development sessions:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 517.95 s    | 306.36 s | 40.85%     |
| uv session                                 | 171.04 s    | 99.42 s  | 41.87%     |
| Codex session                              | 615.86 s    | 348.26 s | 43.45%     |
| ty session                                 | 279.48 s    | 181.93 s | 34.90%     |
| All sessions                               | 1,584.32 s  | 935.98 s | 40.92%     |
| `cargo check`                              | 169.11 s    | 59.99 s  | 64.52%     |
| `cargo test`, `cargo nextest`, `just test` | 902.89 s    | 649.21 s | 28.10%     |
| `cargo clippy`                             | 463.11 s    | 182.26 s | 60.64%     |
| `cargo fmt`                                | 18.53 s     | 13.54 s  | 26.92%     |
| Other commands                             | 28.01 s     | 27.74 s  | 0.98%      |
| All commands                               | 1,581.66 s  | 932.76 s | 41.03%     |

<!-- /benchmark:sessions -->

And comparing disk usage (on APFS):

<!-- benchmark:disk -->

| Scope                 | Rust 1.99.0 | Ohm 1.99.0-6 | Space saved |
| --------------------- | ----------- | ------------ | ----------- |
| Ruff/ty session       | 5.88 GiB    | 3.59 GiB     | 38.87%      |
| Ruff/ty, 2 worktrees  | 10.08 GiB   | 6.17 GiB     | 38.74%      |
| Ruff/ty, 10 worktrees | 52.97 GiB   | 27.00 GiB    | 49.03%      |
| uv session            | 12.13 GiB   | 7.92 GiB     | 34.71%      |
| uv, 2 worktrees       | 16.23 GiB   | 8.64 GiB     | 46.79%      |
| uv, 10 worktrees      | 79.41 GiB   | 33.20 GiB    | 58.19%      |

<!-- /benchmark:disk -->

Compared to the stock Rust toolchain, Ohm:

- Enables (by default) existing experimental features (e.g., parallel compiler frontends).
- Implements experimental, performance-oriented features proposed upstream (e.g.,
  [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790)).
- Fixes various performance bugs and regressions (e.g., around `target/` size increases).
- Implements additional optimizations identified by Codex (e.g., reusing build artifacts between
  `cargo build` and `cargo check`, avoiding rustfmt on unchanged files).

**Warning:** Ohm includes backported and experimental Rust, Cargo, and Clippy optimizations that may
be unsound, including an implementation of
[Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790). This README is
human-edited, but all code changes, PR summaries, and additional documentation were authored
entirely by GPT-6 Astra in Codex. Use Ohm only for local development, and at your own risk.

## Installation

Ohm supports Apple Silicon macOS and x86_64 Linux (glibc). Install [rustup](https://rustup.rs/),
then install the latest Ohm release with our standalone installer:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://labs.astral.sh/ohm/install.sh | sh
```

Ohm's installer verifies its embedded archive checksum, installs the complete Rust toolchain, and
registers an exact version and a moving `ohm` alias with rustup, enabling `cargo +ohm` invocations
(e.g., `cargo +ohm check`).

To install an exact version:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://labs.astral.sh/ohm/releases/ohm-1.99.0-6/install.sh | sh
```

To change the installation directory, set `OHM_INSTALL_DIR`:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://labs.astral.sh/ohm/install.sh \
  | env OHM_INSTALL_DIR=/path/to/toolchain sh
```

## Usage

Use rustup's `+toolchain` syntax to select Ohm:

```console
cargo +ohm test
cargo +ohm check
cargo +ohm clippy
cargo +ohm fmt
```

Exact toolchain names have the form `ohm-<rust-version>-<ohm-revision>`; for example,
`cargo +ohm-1.99.0-6 test` selects that specific installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, proc-macro caching, parallel
compiler frontends, and reuse of previously built registry and workspace dependencies by default.
Opt out with `-Zohm-defaults=no`:

```console
cargo +ohm -Zohm-defaults=no test
```

### `AGENTS.md`

To teach Codex about Ohm, consider adding the following to your `~/.codex/AGENTS.md`:

```markdown
## Ohm Rust toolchain

- Use `cargo +ohm <command>` for all local Cargo commands, including `check`, `test`, `clippy`,
  `fmt`, `metadata`, and external subcommands. Use `rustc +ohm` for direct compiler calls and
  `RUSTUP_TOOLCHAIN=ohm just <recipe>` for task runners.
- Ohm automatically enables `-Zrelink-only`, `-Zpublic-api-hash`, `-Zcache-proc-macros`, and
  `-Zthreads=8` when compiling. Do not inject these flags manually or through `RUSTFLAGS`; direct
  `rustc +ohm` does not receive Cargo's defaults.
- Keep a stable, distinct `CARGO_TARGET_DIR` for each worktree. Set `CARGO_BUILD_BUILD_DIR` to a
  separate shared path for all trusted local projects and worktrees using the same Ohm toolchain.
  Keep the shared build directory separate from every worktree target directory, and do not delete
  it when cleaning up an individual project or worktree.
- Create worktrees for local Rust development from an existing Cargo workspace with
  `cargo +ohm worktree add -b <branch> <path> <base>` to seed reusable build state automatically. If
  using custom target directories, pass the new worktree's target directory via `--target-dir`.
- Set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` to maximize authenticated registry procedural-macro
  reuse across worktrees. On `cargo +ohm worktree add`, this also opts into importing snapshots
  containing local procedural macros. This opt-in is potentially unsound; avoid it for CI, releases,
  etc.
- Set `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all` to maximize reuse of authenticated registry build
  scripts and native-tool helpers across worktrees. This opt-in is potentially unsound; avoid it for
  CI, releases, etc.
- Use `cargo +ohm -Zohm-defaults=no <command>` to disable Ohm's automatic experimental defaults. Use
  plain `cargo <command>` and the repository's normal toolchain for CI and production builds.
```

## Benchmarks

**Developer workflows** measure complete command sequences after an untimed baseline warmup. Each
sequence preserves its build artifacts between commands; each repetition starts from fresh artifacts.

<!-- benchmark:developer-workflows -->

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-6 | Time saved |
| ------- | --------------------------------- | ----------- | ------------ | ---------- |
| Ruff/ty | Edit → focused test               | 14.06 s     | 12.76 s      | 9.28%      |
| Ruff/ty | Edit dependency → downstream test | 13.55 s     | 3.03 s       | 77.67%     |
| Ruff/ty | Edit → check → test → check       | 21.05 s     | 19.26 s      | 8.49%      |
| Ruff/ty | Check → build → check             | 75.14 s     | 52.73 s      | 29.82%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.47 s     | 21.12 s      | 20.21%     |
| uv      | Edit → focused test               | 22.31 s     | 9.49 s       | 57.46%     |
| uv      | Edit dependency → downstream test | 28.52 s     | 3.34 s       | 88.30%     |
| uv      | Edit → check → test → check       | 28.24 s     | 12.75 s      | 54.84%     |
| uv      | Check → build → check             | 142.10 s    | 76.70 s      | 46.02%     |
| uv      | Edit → fmt → clippy → test        | 29.96 s     | 15.38 s      | 48.67%     |
| Codex   | Edit → focused test               | 31.89 s     | 27.81 s      | 12.79%     |
| Codex   | Edit dependency → downstream test | 59.31 s     | 5.57 s       | 90.61%     |
| Codex   | Edit → check → test → check       | 38.44 s     | 36.75 s      | 4.40%      |
| Codex   | Check → build → check             | 186.73 s    | 132.44 s     | 29.07%     |
| Codex   | Edit → fmt → clippy → test        | 44.40 s     | 34.91 s      | 21.38%     |

<!-- /benchmark:developer-workflows -->

These measurements use the published Ohm 1.99.0-6 binaries. The
[build provenance](scripts/benchmark_results/workflow-build.json) records the release, component
sources, and binary hashes.

Each study's cache trust settings are documented in the [benchmark guide](BENCHMARKS.md).

Times are medians of four runs on each project's devbox, including compilation and one focused test
where shown. A failure count replaces the timing if any repetition fails; that row has no speedup.
Edits change the target crate unless labeled as a dependency edit. See the
[workflow definitions and starting states](BENCHMARKS.md#run-the-developer-workflows) and
[individual measurements](scripts/benchmark_results/developer-workflows.json).

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-6 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------ | ------- |
| uv      | `cargo check`          | `uv`         | 2.64 s      | 2.56 s       | 1.03×   |
| uv      | `cargo clippy`         | `uv`         | 4.10 s      | 3.37 s       | 1.22×   |
| uv      | `cargo test --test it` | `uv`         | 21.93 s     | 9.86 s       | 2.22×   |
| Codex   | `cargo check`          | `codex-core` | 5.48 s      | 5.34 s       | 1.03×   |
| Codex   | `just clippy`          | `codex-core` | 26.30 s     | 17.94 s      | 1.47×   |
| Codex   | `just test`            | `codex-core` | 32.87 s     | 28.11 s      | 1.17×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-6 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------ | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 11.95 s     | 0.82 s       | 14.66×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 16.43 s     | 0.87 s       | 18.83×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 24.30 s     | 2.89 s       | 8.41×   |
| Codex   | `cargo check`          | `codex-utils-string` | 21.41 s     | 1.38 s       | 15.51×  |
| Codex   | `just clippy`          | `codex-utils-string` | 49.23 s     | 1.66 s       | 29.59×  |
| Codex   | `just test`            | `codex-utils-string` | 57.59 s     | 4.17 s       | 13.81×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 75.19 s     | 17.93 s | 4.19×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 10.02 s     | 0.83 s  | 12.12×  |
| Codex   | Check after build        | `codex-core`         | 122.23 s    | 37.09 s | 3.30×   |
| Codex   | No-op formatting         | Workspace            | 13.17 s     | 0.45 s  | 29.52×  |
| Codex   | Formatting after an edit | `codex-core`         | 13.72 s     | 0.72 s  | 19.15×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.53 s      | 1.80 s  | 1.96×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 90.09 s     | 52.46 s | 1.72×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 92.20 s     | 9.52 s  | 9.68×   |

<!-- /benchmark:features -->

## Philosophy

Rust's compile times and disk usage are increasingly viewed as bottlenecks in day-to-day
development, especially as agents enable us to parallelize across (dozens of) worktrees.

Ohm enables experimental optimizations to improve Rust's iteration speed and throughput. This is a
deliberate tradeoff: we accept the risks of experimental implementations in local development, where
the blast radius of bugs is comparatively limited and the benefits of faster iteration are
substantial (while continuing to use the official toolchain for production builds).

Ohm is authored entirely by GPT-6 Astra in Codex. Agents lower the cost of implementing, testing,
and refining the ideas explored in this project; good ideas can then be proven out and ultimately
proposed upstream. And by forking the toolchain itself, we can change _anything_; we aren't bounded
by the limitations we'd experience as, e.g., a Cargo wrapper.

At present, Ohm includes the following optimizations, all enabled by default:

- Build release compilers with profile-guided optimization (PGO), plus BOLT on Linux. Apply PGO to
  rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt when supported by the Rust revision.
- Run compiler frontends in parallel.
- [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790): avoid rebuilding
  dependent crates when a dependency's public interface is unchanged (`rustc -Zpublic-api-hash`).
- Cache relinking: reuse compiled code when only the final binary needs to change
  (`cargo -Zrelink-only`).
- Store relink objects per executable, outside dependency search paths, and discard unrelated
  temporary files.
- Find crates by indexing their names and public API hashes, skipping generated object files.
- Index locked dependencies by package name.
- Reuse incremental query dependency edges when promoting cached compiler results.
- Deduplicate metadata for registry and Git dependency libraries.
- Backport faster specialization, privacy checks, and string escaping.
- Skip public API hashing for terminal `cargo check`, `cargo clippy`, and test-harness targets.
- Skip public API hashing for verified immutable registry libraries during cold shared builds.
- Exclude unreachable items from public API hashing.
- Share compiled generic functions across crates.
- Reuse generic-function partitions after edits to private functions or library closures.
- Keep upstream generic instances that capture local closures in the caller's partition.
- Keep codegen-unit merging stable across edits so incremental builds can reuse prior output.
- Reuse encoded metadata prefixes when private edits leave metadata dependencies unchanged.
- Pipeline metadata when a dependency's public API changes.
- Start dependent checks from early interface metadata while upstream function bodies are still
  being checked (`cargo -Zheadstart=no` disables this).
- Reuse integration-test binaries when the edited libraries aren't used by the tests.
- Apply early cutoff to `cargo check` and `cargo clippy`, including with shared registry caches.
- Reuse compiled registry dependencies across builds, checks, tests, and Clippy.
- Reuse compiled workspace dependencies during checks after validating their fingerprints.
- Preserve check graphs across test builds and workspace edits.
- Reuse dependency resolution when only stack, job, or display settings change.
- Use fine-grained build locks that respect file-descriptor limits.
- Avoid repeated compiler-driver validation when reusing registry dependencies.
- Share compiled registry dependencies across worktrees through a separate build directory.
- Avoid duplicate builds when concurrent Cargo invocations need the same registry library with no
  dependencies.
- Format individual changed modules when rustfmt can verify the module graph.
- Cache procedural-macro expansions (`rustc -Zcache-proc-macros`).
- Combine Clippy lint passes and backport faster redundant-clone checks.

Ohm is exclusively intended for local development: never use it for production builds or releases,
and always verify your work with the official Rust toolchain.

Each Ohm release targets a specific upstream Rust release. When a new Rust version becomes
available, we replay the optimizations that remain relevant and drop those that have already landed
upstream. Multiple Ohm revisions may target the same Rust release; for example, `ohm-1.97.1-20` and
`ohm-1.97.1-21`.

For an explanation of the major optimizations and their measured impact, see
[_How Ohm speeds up development_](docs/optimizations.md).

Ohm's patches are maintained in the following repositories:

- [`ohm-rust`](https://github.com/astral-sh/ohm-rust): Rust compiler and standard library.
- [`ohm-cargo`](https://github.com/astral-sh/ohm-cargo): Cargo.
- [`ohm-rust-clippy`](https://github.com/astral-sh/ohm-rust-clippy): Clippy.
- [`ohm-rustfmt`](https://github.com/astral-sh/ohm-rustfmt): rustfmt.

## License

Ohm is licensed under either of

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
  <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>)

at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in Ohm
by you, as defined in the Apache-2.0 license, shall be dually licensed as above, without any
additional terms or conditions.
