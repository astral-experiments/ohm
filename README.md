# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

With Ohm, incremental builds can be up to 41× faster, replayed development sessions take around
44% less time, and `target/` disk usage decreases by around 55%.

Comparing stock Rust and Ohm 1.99.0-24 on replayed development sessions:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 417.50 s    | 227.87 s | 45.42%     |
| uv session                                 | 139.92 s    | 78.09 s  | 44.19%     |
| Codex session                              | 522.78 s    | 288.60 s | 44.80%     |
| ty session                                 | 275.99 s    | 168.35 s | 39.00%     |
| All sessions                               | 1,356.20 s  | 762.90 s | 43.75%     |
| `cargo check`                              | 140.71 s    | 44.46 s  | 68.40%     |
| `cargo test`, `cargo nextest`, `just test` | 783.33 s    | 538.69 s | 31.23%     |
| `cargo clippy`                             | 389.45 s    | 142.27 s | 63.47%     |
| `cargo fmt`                                | 13.94 s     | 8.43 s   | 39.57%     |
| Other commands                             | 27.10 s     | 26.89 s  | 0.79%      |
| All commands                               | 1,354.53 s  | 760.74 s | 43.84%     |

<!-- /benchmark:sessions -->

And comparing disk usage (on APFS):

<!-- benchmark:disk -->

| Scope                 | Rust 1.99.0 | Ohm 1.99.0-11 | Space saved |
| --------------------- | ----------- | ------------- | ----------- |
| Ruff/ty session       | 5.82 GiB    | 3.49 GiB      | 40.06%      |
| Ruff/ty, 2 worktrees  | 10.07 GiB   | 5.91 GiB      | 41.25%      |
| Ruff/ty, 10 worktrees | 52.98 GiB   | 26.46 GiB     | 50.05%      |
| uv session            | 12.09 GiB   | 7.76 GiB      | 35.83%      |
| uv, 2 worktrees       | 16.25 GiB   | 8.55 GiB      | 47.37%      |
| uv, 10 worktrees      | 79.41 GiB   | 32.31 GiB     | 59.31%      |

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
  https://labs.astral.sh/ohm/releases/ohm-1.99.0-9/install.sh | sh
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

Exact toolchain names have the form `ohm-<rust-version>-<ohm-revision>`.
For example, `cargo +ohm-1.99.0-9 test` selects that installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, parallel compiler frontends,
and reuse of previously built registry and workspace dependencies by default.
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
- Ohm automatically enables `-Zrelink-only`, `-Zpublic-api-hash`, and `-Zthreads=8` when compiling.
  Cargo supplies these flags for you. Direct `rustc +ohm` uses its own defaults.
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
Times are medians of four runs, with each toolchain pair measured on the same host. See the
[benchmark guide](BENCHMARKS.md) for details.

<!-- benchmark:developer-workflows -->

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-24 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.94 s     | 12.48 s       | 10.51%     |
| Ruff/ty | Edit dependency → downstream test | 14.53 s     | 12.13 s       | 16.54%     |
| Ruff/ty | Edit → check → test → check       | 20.39 s     | 19.05 s       | 6.57%      |
| Ruff/ty | Check → build → check             | 76.65 s     | 51.11 s       | 33.31%     |
| Ruff/ty | Edit → fmt → clippy → test        | 27.78 s     | 20.15 s       | 27.47%     |
| uv      | Edit → focused test               | 16.82 s     | 8.23 s        | 51.10%     |
| uv      | Edit dependency → downstream test | 18.15 s     | 2.13 s        | 88.26%     |
| uv      | Edit → check → test → check       | 19.10 s     | 10.67 s       | 44.11%     |
| uv      | Check → build → check             | 108.20 s    | 55.83 s       | 48.40%     |
| uv      | Edit → fmt → clippy → test        | 20.56 s     | 12.58 s       | 38.81%     |
| Codex   | Edit → focused test               | 26.53 s     | 24.43 s       | 7.91%      |
| Codex   | Edit dependency → downstream test | 49.91 s     | 3.36 s        | 93.27%     |
| Codex   | Edit → check → test → check       | 36.92 s     | 30.37 s       | 17.74%     |
| Codex   | Check → build → check             | 154.25 s    | 102.06 s      | 33.83%     |
| Codex   | Edit → fmt → clippy → test        | 41.02 s     | 32.27 s       | 21.34%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-24 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 1.98 s      | 1.71 s        | 1.16×   |
| uv      | `cargo clippy`         | `uv`         | 3.09 s      | 2.35 s        | 1.31×   |
| uv      | `cargo test --test it` | `uv`         | 17.20 s     | 8.36 s        | 2.06×   |
| Codex   | `cargo check`          | `codex-core` | 4.22 s      | 3.99 s        | 1.06×   |
| Codex   | `just clippy`          | `codex-core` | 19.87 s     | 13.06 s       | 1.52×   |
| Codex   | `just test`            | `codex-core` | 26.87 s     | 25.82 s       | 1.04×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-24 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 8.73 s      | 0.43 s        | 20.48×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.41 s     | 0.54 s        | 22.95×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 18.62 s     | 2.06 s        | 9.05×   |
| Codex   | `cargo check`          | `codex-utils-string` | 16.93 s     | 0.71 s        | 23.85×  |
| Codex   | `just clippy`          | `codex-utils-string` | 40.12 s     | 0.97 s        | 41.58×  |
| Codex   | `just test`            | `codex-utils-string` | 48.81 s     | 3.05 s        | 16.03×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 57.99 s     | 12.64 s | 4.59×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.56 s      | 0.65 s  | 10.17×  |
| Codex   | Check after build        | `codex-core`         | 104.50 s    | 28.75 s | 3.63×   |
| Codex   | No-op formatting         | Workspace            | 9.54 s      | 0.18 s  | 52.49×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.68 s      | 0.25 s  | 38.05×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.58 s      | 0.60 s  | 4.30×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 88.80 s     | 49.46 s | 1.80×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 88.59 s     | 8.89 s  | 9.96×   |

<!-- /benchmark:features -->

**Doctests** show how long it takes to rerun Ruff's documentation examples with unchanged source:

<!-- benchmark:ruff-doctests -->

| Workload                           | Rust 1.99.0 | Ohm 1.99.0-24 | Speedup |
| ---------------------------------- | ----------- | ------------- | ------- |
| Ruff doctests (`cargo test --doc`) | 13.567 s    | 1.542 s       | 8.80×   |

<!-- /benchmark:ruff-doctests -->

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
