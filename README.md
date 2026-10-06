# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

With Ohm, incremental builds can be up to 30× faster, replayed development sessions take around
37% less time, and `target/` disk usage decreases by around 55%.

Benchmarking Ohm 1.99.0-2 against stock Rust on replayed development sessions:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm 1.99.0-2 | Time saved |
| ------------------------------------------ | ----------- | ------------ | ---------- |
| Ruff session                               | 438.46 s    | 286.58 s     | 34.64%     |
| uv session                                 | 144.04 s    | 93.94 s      | 34.78%     |
| Codex session                              | 535.54 s    | 324.34 s     | 39.44%     |
| All sessions                               | 1,118.04 s  | 704.86 s     | 36.96%     |
| `cargo check`                              | 144.08 s    | 46.91 s      | 67.44%     |
| `cargo test`, `cargo nextest`, `just test` | 627.07 s    | 496.18 s     | 20.87%     |
| `cargo clippy`                             | 330.65 s    | 148.50 s     | 55.09%     |
| `cargo fmt`                                | 14.27 s     | 11.20 s      | 21.51%     |
| All commands                               | 1,116.07 s  | 702.79 s     | 37.03%     |

<!-- /benchmark:sessions -->

And comparing disk usage (on APFS):

<!-- benchmark:disk -->

| Scope                 | Rust 1.99.0 | Ohm 1.99.0-2 | Space saved |
| --------------------- | ----------- | ------------ | ----------- |
| Ruff/ty session       | 5.91 GiB    | 3.54 GiB     | 40.13%      |
| Ruff/ty, 2 worktrees  | 10.13 GiB   | 6.00 GiB     | 40.82%      |
| Ruff/ty, 10 worktrees | 53.04 GiB   | 26.30 GiB    | 50.42%      |
| uv session            | 12.14 GiB   | 7.90 GiB     | 34.95%      |
| uv, 2 worktrees       | 16.26 GiB   | 8.64 GiB     | 46.88%      |
| uv, 10 worktrees      | 79.47 GiB   | 33.21 GiB    | 58.21%      |

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
  https://labs.astral.sh/ohm/releases/ohm-1.99.0-2/install.sh | sh
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
`cargo +ohm-1.99.0-2 test` selects that specific installed revision.

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

See the [benchmark documentation](./BENCHMARKS.md) for instructions on running these benchmarks.

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-2 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------ | ------- |
| uv      | `cargo check`          | `uv`         | 2.88 s      | 3.01 s       | 0.96×   |
| uv      | `cargo clippy`         | `uv`         | 3.52 s      | 2.87 s       | 1.23×   |
| uv      | `cargo test --test it` | `uv`         | 22.20 s     | 11.02 s      | 2.02×   |
| Codex   | `cargo check`          | `codex-core` | 6.13 s      | 6.14 s       | 1.00×   |
| Codex   | `just clippy`          | `codex-core` | 21.09 s     | 15.25 s      | 1.38×   |
| Codex   | `just test`            | `codex-core` | 33.13 s     | 26.96 s      | 1.23×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-2 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------ | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 11.18 s     | 1.09 s       | 10.28×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 14.15 s     | 0.74 s       | 19.13×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 23.15 s     | 3.41 s       | 6.80×   |
| Codex   | `cargo check`          | `codex-utils-string` | 19.91 s     | 1.48 s       | 13.44×  |
| Codex   | `just clippy`          | `codex-utils-string` | 43.66 s     | 1.44 s       | 30.42×  |
| Codex   | `just test`            | `codex-utils-string` | 52.33 s     | 4.93 s       | 10.61×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and safe cross-worktree builds:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm 1.99.0-2 | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------------ | ------- |
| uv      | Build, then check        | `uv`                 | 66.46 s     | 18.98 s      | 3.50×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 9.01 s      | 1.01 s       | 8.95×   |
| Codex   | Build, then check        | `codex-core`         | 111.64 s    | 44.83 s      | 2.49×   |
| Codex   | No-op formatting         | Workspace            | 10.25 s     | 0.29 s       | 34.87×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.71 s      | 0.43 s       | 22.40×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.43 s      | 0.77 s       | 4.44×   |

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
