# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

With Ohm, incremental builds can be up to 37× faster, real-world development sessions see around a
38% speed-up, and `target/` disk usage decreases by around 50%.

Benchmarking Ohm 1.98.0-11 against stock Rust on replayed development sessions:

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-11 | Time saved |
| ------------------------------------------ | ----------: | ------------: | ---------: |
| Ruff session                               |    540.38 s |      354.78 s |     34.35% |
| uv session                                 |    183.57 s |      138.59 s |     24.51% |
| Codex session                              |    688.31 s |      375.20 s |     45.49% |
| All sessions                               |  1,412.26 s |      868.57 s |     38.50% |
| `cargo check`                              |    180.62 s |       62.11 s |     65.61% |
| `cargo test`, `cargo nextest`, `just test` |    798.70 s |      593.05 s |     25.75% |
| `cargo clippy`                             |    411.88 s |      196.55 s |     52.28% |
| `cargo fmt`                                |     19.16 s |       14.82 s |     22.65% |
| All commands                               |  1,410.35 s |      866.53 s |     38.56% |

And comparing disk usage (on APFS):

| Scope                 | Rust 1.98.0 | Ohm 1.98.0-11 | Space saved |
| --------------------- | ----------: | ------------: | ----------: |
| Ruff/ty session       |    6.01 GiB |      3.49 GiB |      41.97% |
| Ruff/ty, 2 worktrees  |   10.38 GiB |      5.96 GiB |      42.52% |
| Ruff/ty, 10 worktrees |   54.16 GiB |     26.11 GiB |      51.79% |
| uv session            |   13.02 GiB |     10.78 GiB |      17.22% |
| uv, 2 worktrees       |   17.48 GiB |     11.63 GiB |      33.48% |
| uv, 10 worktrees      |   85.45 GiB |     44.97 GiB |      47.37% |

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
  https://labs.astral.sh/ohm/releases/ohm-1.98.0-11/install.sh | sh
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
`cargo +ohm-1.98.0-11 test` selects that specific installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, proc-macro caching, parallel
compiler frontends, and reuse of previously built registry and workspace dependencies by default.
Opt out with `-Zohm-defaults=no`:

```console
cargo +ohm -Zohm-defaults=no test
```

Native x86_64 Linux GNU builds use the bundled upstream Wild linker by default.
Use `-Zohm-linker=lld` to select LLD; explicit linker settings take precedence.

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

See the [benchmark documentation](./BENCHMARKS.md) for instructions on running these benchmarks.

**Direct edits** modify the crate being checked, linted, or tested:

| Project | Workflow               | Edited crate | Rust 1.98.0 | Ohm 1.98.0-11 | Speedup |
| ------- | ---------------------- | ------------ | ----------: | ------------: | ------: |
| uv      | `cargo check`          | `uv`         |      3.40 s |        3.31 s |   1.03× |
| uv      | `cargo clippy`         | `uv`         |      4.50 s |        3.37 s |   1.34× |
| uv      | `cargo test --test it` | `uv`         |     24.86 s |       15.84 s |   1.57× |
| Codex   | `cargo check`          | `codex-core` |      7.22 s |        6.67 s |   1.08× |
| Codex   | `just clippy`          | `codex-core` |     25.92 s |       17.30 s |   1.50× |
| Codex   | `just test`            | `codex-core` |     38.69 s |       28.47 s |   1.36× |

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

| Project | Workflow               | Edited dependency    | Rust 1.98.0 | Ohm 1.98.0-11 | Speedup |
| ------- | ---------------------- | -------------------- | ----------: | ------------: | ------: |
| uv      | `cargo check`          | `uv-normalize`       |     13.78 s |        1.15 s |  11.97× |
| uv      | `cargo clippy`         | `uv-normalize`       |     19.08 s |        0.80 s |  23.87× |
| uv      | `cargo test --test it` | `uv-normalize`       |     28.66 s |        5.65 s |   5.07× |
| Codex   | `cargo check`          | `codex-utils-string` |     23.73 s |        1.56 s |  15.22× |
| Codex   | `just clippy`          | `codex-utils-string` |     53.13 s |        1.40 s |  37.82× |
| Codex   | `just test`            | `codex-utils-string` |     63.94 s |        5.05 s |  12.66× |

**Other common cases** include build-to-check reuse, formatting, and safe cross-worktree builds:

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-11 | Speedup |
| ------- | ------------------------ | -------------------- | ----------: | ------------: | ------: |
| uv      | Build, then check        | `uv`                 |     80.00 s |       21.86 s |   3.66× |
| uv      | Shared-worktree build    | `uv-normalize`       |     10.80 s |        1.09 s |   9.90× |
| Codex   | Build, then check        | `codex-core`         |    135.40 s |       59.18 s |   2.29× |
| Codex   | No-op formatting         | Workspace            |     12.93 s |        0.46 s |  28.22× |
| Codex   | Formatting after an edit | `codex-core`         |     12.87 s |        0.52 s |  24.94× |
| Codex   | Shared-worktree build    | `codex-utils-string` |      4.54 s |        1.19 s |   3.81× |

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
