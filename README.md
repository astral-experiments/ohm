# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for extremely fast local development. With Ohm,
incremental builds can be up to 32x faster for common commands in large workspaces.

**Direct edits** modify the crate being checked, linted, or tested:

| Project | Workflow               | Edited crate | Rust 1.97.1 | Ohm 1.97.1-12 | Speedup |
| ------- | ---------------------- | ------------ | ----------: | ------------: | ------: |
| uv      | `cargo check`          | `uv`         |      0.95 s |        0.87 s |   1.10× |
| uv      | `cargo clippy`         | `uv`         |      2.07 s |        1.32 s |   1.57× |
| uv      | `cargo test --test it` | `uv`         |      8.49 s |        5.87 s |   1.45× |
| Codex   | `cargo check`          | `codex-core` |      2.10 s |        2.07 s |   1.02× |
| Codex   | `just clippy`          | `codex-core` |     11.67 s |        7.36 s |   1.58× |
| Codex   | `just test`            | `codex-core` |     14.43 s |       12.12 s |   1.19× |

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

| Project | Workflow               | Edited dependency    | Rust 1.97.1 | Ohm 1.97.1-12 | Speedup |
| ------- | ---------------------- | -------------------- | ----------: | ------------: | ------: |
| uv      | `cargo check`          | `uv-normalize`       |      4.51 s |        0.32 s |  14.15× |
| uv      | `cargo clippy`         | `uv-normalize`       |      8.99 s |        0.37 s |  24.16× |
| uv      | `cargo test --test it` | `uv-normalize`       |     13.28 s |        3.97 s |   3.35× |
| Codex   | `cargo check`          | `codex-utils-string` |      7.93 s |        0.57 s |  14.03× |
| Codex   | `just clippy`          | `codex-utils-string` |     23.57 s |        0.73 s |  32.07× |
| Codex   | `just test`            | `codex-utils-string` |     26.35 s |        6.41 s |   4.11× |

**Other common cases** include build-to-check reuse, formatting, and safe cross-worktree builds:

| Project | Workflow                 | Package              | Rust 1.97.1 | Ohm 1.97.1-12 | Speedup |
| ------- | ------------------------ | -------------------- | ----------: | ------------: | ------: |
| uv      | Build, then check        | `uv`                 |     36.45 s |       17.14 s |   2.13× |
| uv      | Shared-worktree build    | `uv-normalize`       |      4.01 s |        2.97 s |   1.35× |
| Codex   | Build, then check        | `codex-core`         |     60.93 s |       37.14 s |   1.64× |
| Codex   | No-op formatting         | Workspace            |      5.04 s |        0.89 s |   5.67× |
| Codex   | Formatting after an edit | `codex-core`         |      5.12 s |        3.11 s |   1.65× |
| Codex   | Shared-worktree build    | `codex-utils-string` |      1.62 s |        0.32 s |   5.01× |

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
  https://labs.astral.sh/ohm/releases/ohm-1.97.1-15/install.sh | sh
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
`cargo +ohm-1.97.1-15 test` selects that specific installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, proc-macro caching, and reuse of
previously built registry dependencies by default. Use its aggregate opt-out to compare against the
same compiler and Cargo without those defaults:

```console
cargo +ohm -Zohm-defaults=no test
```

`cargo +ohm fmt` also formats only changed workspace packages and, when rustfmt can safely verify a
changed module in isolation, just that module. Set `OHM_INCREMENTAL_FMT=0` to disable incremental
formatting.

To share immutable registry artifacts across worktrees, configure the same separate build directory
for each checkout:

```console
CARGO_BUILD_BUILD_DIR=/path/to/shared-build cargo +ohm build
```

Workspace artifacts and final outputs remain private to each checkout. Sharing is disabled when the
build directory overlaps a checkout's target directory, Ohm's defaults are turned off, or native
build tools resolve to unverified user-controlled wrappers.

Registry procedural macros and their runtime dependencies are shared only after source and checksum
verification. By default, Ohm limits sharing to individually audited macro releases. To explicitly
trust all authenticated registry macros, use `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` or
`cargo +ohm -Zohm-proc-macro-trust=all build`. This mode is potentially unsound: macros can read
untracked files or environment variables, use randomness, and produce stale generated code or omit
diagnostics. Strict and permissive artifacts remain isolated; build-to-check reuse stays audited.

### `AGENTS.md`

To teach Codex about Ohm, consider adding the following to your `~/.codex/AGENTS.md`:

```markdown
## Ohm Rust toolchain

- Use `cargo +ohm <command>` for all local Cargo commands, including `check`, `test`, `clippy`,
  `fmt`, `metadata`, and external subcommands. Use `rustc +ohm` for direct compiler calls and
  `RUSTUP_TOOLCHAIN=ohm just <recipe>` for task runners.
- Ohm automatically enables `-Zrelink-only`, `-Zpublic-api-hash`, and `-Zcache-proc-macros` when
  compiling. Do not inject these flags manually or through `RUSTFLAGS`; direct `rustc +ohm` does not
  receive Cargo's defaults.
- Keep a stable, distinct `CARGO_TARGET_DIR` for each worktree. Set `CARGO_BUILD_BUILD_DIR` to a
  separate shared path for worktrees using the same repository and Ohm toolchain.
- Use `cargo +ohm -Zohm-defaults=no <command>` to disable Ohm's automatic experimental defaults. Use
  plain `cargo <command>` and the repository's normal toolchain for CI and production builds.
```

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
- Indexed locked dependencies by package name while preserving aliases and multiple versions.
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
- Reused immutable registry dependencies between builds, checks, and Clippy invocations, including
  active dependency graphs and audited procedural-macro closures, without speculative dependency
  resolution before a prior build.
- Deduplicated authenticated compiler-driver validation across reused registry dependencies.
- Shared immutable registry artifacts across worktrees with an explicitly configured build directory,
  including audited procedural-macro and runtime-dependency closures, standard native pthread
  linkage, and authenticated Linux LLVM tools.
- Incremental workspace formatting that formats individual changed modules when rustfmt's
  authoritative module graph confirms their ownership and topology, with buffered incremental state
  and module manifests and reused source observations.
- Experimental procedural-macro caching (`rustc -Zcache-proc-macros`).
- Backported Clippy optimizations, including combined lint passes and redundant-clone fast paths.

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
upstream. Multiple Ohm revisions may target the same Rust release; for example, `ohm-1.97.1-14` and
`ohm-1.97.1-15`.

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
