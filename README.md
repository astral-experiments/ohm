# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for extremely fast local development. With Ohm,
incremental builds can be up to 22x faster for common commands in large workspaces.

The tables summarize a complete 192-sample study; additional formatting, build-to-check, and
shared-worktree scenarios are described in the [benchmark methodology](BENCHMARKS.md).

**Direct edits** modify the crate being checked, linted, or tested:

| Project | Workflow       | Edited crate | Rust 1.97.1 | Ohm 1.97.1-11 | Speedup |
| ------- | -------------- | ------------ | ----------: | ------------: | ------: |
| uv      | `cargo check`  | `uv`         |      0.94 s |        1.02 s |   0.93× |
| uv      | `cargo clippy` | `uv`         |      2.08 s |        1.49 s |   1.40× |
| uv      | `cargo test`   | `uv`         |      7.12 s |        3.24 s |   2.20× |
| Codex   | `cargo check`  | `codex-core` |      1.93 s |        2.09 s |   0.92× |
| Codex   | `just clippy`  | `codex-core` |     12.18 s |        8.31 s |   1.47× |
| Codex   | `just test`    | `codex-core` |     15.10 s |       13.08 s |   1.15× |

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

| Project | Workflow       | Edited dependency    | Rust 1.97.1 | Ohm 1.97.1-11 | Speedup |
| ------- | -------------- | -------------------- | ----------: | ------------: | ------: |
| uv      | `cargo check`  | `uv-normalize`       |      4.50 s |        0.47 s |   9.49× |
| uv      | `cargo clippy` | `uv-normalize`       |      8.82 s |        0.53 s |  16.68× |
| uv      | `cargo test`   | `uv-normalize`       |     10.56 s |        1.71 s |   6.18× |
| Codex   | `cargo check`  | `codex-utils-string` |      7.83 s |        0.87 s |   9.02× |
| Codex   | `just clippy`  | `codex-utils-string` |     23.44 s |        1.06 s |  22.11× |
| Codex   | `just test`    | `codex-utils-string` |     26.44 s |        6.21 s |   4.26× |

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
  https://labs.astral.sh/ohm/releases/ohm-1.97.1-12/install.sh | sh
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
`cargo +ohm-1.97.1-12 test` selects that specific installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, proc-macro caching, and reuse of
previously built registry dependencies by default. Use its aggregate opt-out to compare against the
same compiler and Cargo without those defaults:

```console
cargo +ohm -Zohm-defaults=no test
```

`cargo +ohm fmt` also formats only the workspace packages that changed. Set
`OHM_INCREMENTAL_FMT=0` to disable incremental formatting.

To share immutable registry artifacts across worktrees, configure the same separate build directory
for each checkout:

```console
CARGO_BUILD_BUILD_DIR=/path/to/shared-build cargo +ohm build
```

Workspace artifacts and final outputs remain private to each checkout. Sharing is disabled when the
build directory overlaps a checkout's target directory, Ohm's defaults are turned off, or native
build tools resolve to unverified user-controlled wrappers.

## Philosophy

Rust's compile times are a bottleneck in day-to-day development, especially in large workspaces
where changing one crate can trigger unnecessary work throughout the dependency graph.

Ohm makes a deliberate tradeoff: faster local iteration is more valuable than waiting for every
optimization to meet upstream Rust's standards for completeness and correctness. We backport
improvements from newer Rust releases, pull forward work that has not yet landed upstream, and
experiment with optimizations that may still contain bugs.

At present, Ohm includes the following optimizations, all enabled by default:

- [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790): avoid rebuilding
  dependent crates when a dependency's public interface is unchanged (`rustc -Zpublic-api-hash`).
- Cached relinking: reuse existing code generation when only the final binary needs to change
  (`cargo -Zrelink-only`).
- Per-executable relink caches that keep generated object files out of dependency search paths.
- Retained relink objects without unrelated compiler temporaries, saving 766–841 MiB in controlled
  Codex and uv target-directory comparisons.
- Faster crate discovery by ignoring generated object files during compiler search-path indexing.
- Indexed crate lookup by name and public API hash (13% faster on a Codex dependency-graph fixture).
- Reused incremental query dependency edges during compiler cache promotion.
- Deduplicated metadata for registry and Git dependency libraries.
- Backported compiler fast paths for specialization, privacy checking, and string escaping.
- Skipped public API hashing for terminal `cargo check` and `cargo clippy` targets.
- Reachability-pruned public API hashing for crates that still require it.
- Shared generic monomorphizations across crates, with public API hashes tracking reusable symbols.
- Reused monomorphization partitions after private function and library-closure edits.
- Caller-local partitioning of upstream generic instances that capture local closures.
- Stable incremental codegen-unit merging that preserves reusable work products across edits.
- Reused encoded metadata prefixes when private edits preserve metadata dependencies.
- Conditional metadata pipelining when a dependency's public API changes, with crash-safe recovery.
- Reused integration-test executables when changed package or workspace libraries are unused.
- Early cutoff for `cargo check` and `cargo clippy`.
- Reused immutable registry dependencies between builds, checks, and Clippy invocations, without
  speculative dependency resolution before a prior build.
- Shared immutable registry artifacts across worktrees with an explicitly configured build directory,
  including standard native pthread linkage and authenticated Linux LLVM tools.
- Incremental workspace formatting backed by rustfmt's authoritative module graph.
- Experimental procedural-macro caching (`rustc -Zcache-proc-macros`).
- Backported Clippy optimizations, including combined lint passes.

Ohm also includes explicitly requested, experimental focused test compilation. To compile only one
exact library test, pass `-Zohm-focused-tests` before the Cargo subcommand:

```console
cargo +ohm -Zohm-focused-tests test -p <package> --lib <full-test-name> -- --exact
```

This mode is not enabled by default, does not support nextest discovery or coverage, and can omit
backend or linker diagnostics from unselected tests.

Ohm is exclusively intended for local development: never use it for production builds or releases,
and always verify your work with the official Rust toolchain.

Each Ohm release targets a specific upstream Rust release. When a new Rust version becomes
available, we replay the optimizations that remain relevant and drop those that have already landed
upstream. Multiple Ohm revisions may target the same Rust release; for example, `ohm-1.97.1-11` and
`ohm-1.97.1-12`.

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
