# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for extremely fast local development. With Ohm,
incremental builds can be up to 33× faster, real-world development sessions see around a 37% speed-up,
and each worktree saves multiple gigabytes of disk space.

Benchmarking Ohm 1.98.0-5 against stock Rust on replayed development sessions:

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    528.74 s |     343.08 s |   185.67 s |    35.11% |
| uv session                                 |    190.85 s |     145.76 s |    45.09 s |    23.63% |
| Codex session                              |    693.53 s |     403.14 s |   290.39 s |    41.87% |
| All sessions                               |  1,413.12 s |     891.97 s |   521.15 s |    36.88% |
| `cargo check`                              |    193.47 s |      70.80 s |   122.67 s |    63.41% |
| `cargo test`, `cargo nextest`, `just test` |    785.24 s |     613.34 s |   171.89 s |    21.89% |
| `cargo clippy`                             |    413.95 s |     192.16 s |   221.78 s |    53.58% |
| `cargo fmt`                                |     18.56 s |      13.33 s |     5.22 s |    28.16% |
| All commands                               |  1,411.21 s |     889.64 s |   521.58 s |    36.96% |

Compared to the stock Rust toolchain, Ohm:

- Enables (by default) existing experimental features (e.g., parallel compiler frontends).
- Implements experimental, performance-oriented features proposed upstream (e.g.,
  [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790)).
- Implements additional optimizations identified by Codex (e.g., reusing build artifacts between
  `cargo build` and `cargo check`, avoiding rustfmt on unchanged files).

**Warning:** Ohm includes backported and experimental Rust, Cargo, and Clippy optimizations that may
be unsound, including an implementation of
[Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790). Use it only for
local development, and at your own risk.

## Installation

Ohm supports Apple Silicon macOS and x86_64 Linux (glibc). Install [rustup](https://rustup.rs/), then
install the latest Ohm release with our standalone installer:

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
  https://labs.astral.sh/ohm/releases/ohm-1.98.0-5/install.sh | sh
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
`cargo +ohm-1.98.0-5 test` selects that specific installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, proc-macro caching, parallel
compiler frontends, and reuse of previously built registry and workspace dependencies by default.
Use its aggregate opt-out to compare against the same compiler and Cargo without those defaults:

```console
cargo +ohm -Zohm-defaults=no test
```

`cargo +ohm fmt` also formats only changed workspace packages and, when rustfmt can safely verify a
changed module in isolation, just that module. Set `OHM_INCREMENTAL_FMT=0` to disable incremental
formatting.

To share immutable registry artifacts across projects and worktrees using the same Ohm toolchain,
configure the same separate build directory for each checkout:

```console
CARGO_BUILD_BUILD_DIR=/path/to/shared-build cargo +ohm build
```

To compile only one exact library test, enable experimental focused test compilation:

```console
cargo +ohm -Zohm-focused-tests test -p <package> --lib <full-test-name> -- --exact
```

This mode is not enabled by default, does not support nextest discovery or coverage, and can omit
backend or linker diagnostics from unselected tests.

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
- Set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` to maximize authenticated registry procedural-macro
  reuse across worktrees. This opt-in is potentially unsound; avoid it for CI, releases, etc.
- Set `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all` to maximize reuse of authenticated registry build
  scripts and native-tool helpers across worktrees. This opt-in is potentially unsound; avoid it for
  CI, releases, etc.
- Use `cargo +ohm -Zohm-defaults=no <command>` to disable Ohm's automatic experimental defaults. Use
  plain `cargo <command>` and the repository's normal toolchain for CI and production builds.
```

## Benchmarks

These results were measured with Ohm 1.98.0-5, not the current release. See the
[benchmark documentation](./BENCHMARKS.md) for the full results and methodology.

**Direct edits (Linux devbox)** modify the crate being checked, linted, or tested:

| Project | Workflow               | Edited crate | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup |
| ------- | ---------------------- | ------------ | ----------: | -----------: | ------: |
| uv      | `cargo check`          | `uv`         |      2.34 s |       2.12 s |   1.10× |
| uv      | `cargo clippy`         | `uv`         |      3.56 s |       3.11 s |   1.14× |
| uv      | `cargo test --test it` | `uv`         |     18.18 s |      10.84 s |   1.68× |
| Codex   | `cargo check`          | `codex-core` |      4.41 s |       3.88 s |   1.14× |
| Codex   | `just clippy`          | `codex-core` |     18.83 s |      14.68 s |   1.28× |
| Codex   | `just test`            | `codex-core` |     26.40 s |      23.44 s |   1.13× |

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

| Project | Workflow               | Edited dependency    | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup |
| ------- | ---------------------- | -------------------- | ----------: | -----------: | ------: |
| uv      | `cargo check`          | `uv-normalize`       |     10.76 s |       0.57 s |  18.85× |
| uv      | `cargo clippy`         | `uv-normalize`       |     14.69 s |       0.63 s |  23.27× |
| uv      | `cargo test --test it` | `uv-normalize`       |     20.99 s |       4.12 s |   5.10× |
| Codex   | `cargo check`          | `codex-utils-string` |     17.67 s |       1.00 s |  17.68× |
| Codex   | `just clippy`          | `codex-utils-string` |     38.80 s |       1.18 s |  33.00× |
| Codex   | `just test`            | `codex-utils-string` |     46.07 s |       7.07 s |   6.51× |

**Other common cases** include build-to-check reuse, formatting, and safe cross-worktree builds:

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.73 s |      17.98 s |   3.54× |
| uv      | Shared-worktree build    | `uv-normalize`       |      7.00 s |       0.49 s |  14.16× |
| Codex   | Build, then check        | `codex-core`         |    105.38 s |      47.81 s |   2.20× |
| Codex   | No-op formatting         | Workspace            |     11.11 s |       0.32 s |  34.64× |
| Codex   | Formatting after an edit | `codex-core`         |     11.07 s |       0.52 s |  21.18× |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.81 s |       0.61 s |   4.61× |

## Philosophy

Rust's compile times are a bottleneck in day-to-day development, especially in large workspaces
where changing one crate can trigger unnecessary work throughout the dependency graph.

Ohm makes a deliberate tradeoff: faster local iteration is more valuable than waiting for every
optimization to meet upstream Rust's standards for completeness and correctness. We backport
improvements from newer Rust releases, pull forward work that has not yet landed upstream, and
experiment with optimizations that may still contain bugs.

At present, Ohm includes the following optimizations, all enabled by default:

- Release compilers optimized with profile-guided training on macOS and Linux, with
  component-PGO-capable Rust revisions additionally optimizing rustdoc, Cargo, Clippy, rustfmt,
  and cargo-fmt. Linux releases also apply compiler BOLT optimization.
- Parallel compiler frontends enabled by default, with bounded parallel-query recursion and
  preserved explicit thread-count and crate recursion-limit overrides.
- [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790): avoid rebuilding
  dependent crates when a dependency's public interface is unchanged (`rustc -Zpublic-api-hash`).
- Cached relinking: reuse existing code generation when only the final binary needs to change
  (`cargo -Zrelink-only`).
- Per-executable relink caches that keep generated object files out of dependency search paths.
- Retained relink objects without unrelated compiler temporaries, saving 766–841 MiB in controlled
  Codex and uv target-directory comparisons.
- Faster crate discovery by ignoring generated object files during compiler search-path indexing.
- Indexed crate lookup by name and public API hash (13% faster on a Codex dependency-graph fixture).
- Indexed locked dependencies by package name while preserving aliases and multiple versions.
- Reused incremental query dependency edges during compiler cache promotion.
- Deduplicated metadata for registry and Git dependency libraries.
- Backported compiler fast paths for specialization, privacy checking, and string escaping.
- Skipped public API hashing for terminal `cargo check`, `cargo clippy`, and test-harness targets.
- Skipped public API hashing for authenticated immutable registry libraries during cold shared builds.
- Reachability-pruned public API hashing for crates that still require it.
- Shared generic monomorphizations across crates, with public API hashes tracking reusable symbols.
- Reused monomorphization partitions after private function and library-closure edits.
- Caller-local partitioning of upstream generic instances that capture local closures.
- Stable incremental codegen-unit merging that preserves reusable work products across edits.
- Reused encoded metadata prefixes when private edits preserve metadata dependencies.
- Conditional metadata pipelining when a dependency's public API changes, with crash-safe recovery.
- Reused integration-test executables when changed package or workspace libraries are unused.
- Early cutoff for `cargo check` and `cargo clippy`, including with shared registry caches.
- Reused immutable registry dependencies between builds, checks, test graphs, and Clippy invocations,
  including active dependency graphs and audited procedural-macro closures, without speculative
  dependency resolution before a prior build.
- Reused fresh, already-built workspace dependency libraries during subsequent checks, with complete
  fingerprint validation and the explicitly selected authenticated procedural-macro trust policy.
- Preserved established check graphs across test builds and workspace edits, with lock-safe shared
  registry fingerprints and cold-build fallback.
- Resolver cache reuse across changes to execution-only stack, job, and display settings.
- File-descriptor-aware fine-grained build locking that stays within the process limit.
- Deduplicated authenticated compiler-driver validation across reused registry dependencies.
- Shared immutable registry artifacts across worktrees with an explicitly configured build directory,
  including audited procedural-macro and runtime-dependency closures, dependency-scoped native-tool
  isolation, standard native pthread linkage, authenticated Linux LLVM tools, and checksum-authenticated
  crates.io packages fetched through HTTP(S) registry mirrors.
- Coalesced concurrent cache misses for authenticated registry libraries without dependencies,
  avoiding duplicate compilation when another Cargo invocation completes the same shared artifact.
- Incremental workspace formatting that formats individual changed modules when rustfmt's
  authoritative module graph confirms their ownership and topology, with buffered incremental state,
  reused clean checks and configuration snapshots, batched independent leaf modules, and avoided
  unnecessary topology discovery and no-write reverification.
- Experimental procedural-macro caching (`rustc -Zcache-proc-macros`).
- Backported Clippy optimizations, including combined lint passes and redundant-clone fast paths.

Ohm is exclusively intended for local development: never use it for production builds or releases,
and always verify your work with the official Rust toolchain.

Each Ohm release targets a specific upstream Rust release. When a new Rust version becomes
available, we replay the optimizations that remain relevant and drop those that have already landed
upstream. Multiple Ohm revisions may target the same Rust release; for example, `ohm-1.97.1-20` and
`ohm-1.97.1-21`.

See [_Changes from upstream_](docs/upstream-changes.md) for the complete list of included patches;
patches are maintained in peer repositories:

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
