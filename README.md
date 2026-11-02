# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

With Ohm, incremental builds can be up to 9× faster, replayed development sessions take around
4% less time, and `target/` disk usage decreases by around 55%.

Comparing stock Rust and Ohm on replayed development sessions:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm        | Time saved |
| ------------------------------------------ | ----------- | ---------- | ---------- |
| Ruff session                               | 679.99 s    | 362.93 s   | 46.63%     |
| uv session                                 | 173.28 s    | 98.90 s    | 42.93%     |
| Codex session                              | 617.74 s    | 1,075.88 s | −74.17%    |
| ty session                                 | 352.43 s    | 204.92 s   | 41.85%     |
| All sessions                               | 1,823.43 s  | 1,742.64 s | 4.43%      |
| `cargo check`                              | 172.59 s    | 58.27 s    | 66.24%     |
| `cargo test`, `cargo nextest`, `just test` | 1,028.12 s  | 1,440.05 s | −40.07%    |
| `cargo clippy`                             | 566.24 s    | 204.83 s   | 63.83%     |
| `cargo fmt`                                | 20.43 s     | 13.68 s    | 33.03%     |
| Other commands                             | 33.00 s     | 22.36 s    | 32.24%     |
| All commands                               | 1,820.37 s  | 1,739.18 s | 4.46%      |

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

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-22 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 16.78 s     | 18.64 s       | −11.11%    |
| Ruff/ty | Edit dependency → downstream test | 17.05 s     | 16.31 s       | 4.33%      |
| Ruff/ty | Edit → check → test → check       | 25.76 s     | 27.20 s       | −5.60%     |
| Ruff/ty | Check → build → check             | 99.08 s     | 66.32 s       | 33.06%     |
| Ruff/ty | Edit → fmt → clippy → test        | 35.00 s     | 29.64 s       | 15.34%     |
| uv      | Edit → focused test               | 21.54 s     | 12.68 s       | 41.11%     |
| uv      | Edit dependency → downstream test | 27.31 s     | 4.37 s        | 83.99%     |
| uv      | Edit → check → test → check       | 27.76 s     | 18.80 s       | 32.27%     |
| uv      | Check → build → check             | 140.67 s    | 74.90 s       | 46.75%     |
| uv      | Edit → fmt → clippy → test        | 29.51 s     | 19.95 s       | 32.40%     |
| Codex   | Edit → focused test               | 32.87 s     | 75.54 s       | −129.82%   |
| Codex   | Edit dependency → downstream test | 62.58 s     | 71.78 s       | −14.70%    |
| Codex   | Edit → check → test → check       | 45.21 s     | 142.18 s      | −214.47%   |
| Codex   | Check → build → check             | 200.76 s    | 189.06 s      | 5.83%      |
| Codex   | Edit → fmt → clippy → test        | 46.61 s     | 116.82 s      | −150.64%   |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-22 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.57 s      | 3.38 s        | 0.76×   |
| uv      | `cargo clippy`         | `uv`         | 3.97 s      | 4.39 s        | 0.90×   |
| uv      | `cargo test --test it` | `uv`         | 21.83 s     | 12.21 s       | 1.79×   |
| Codex   | `cargo check`          | `codex-core` | 5.28 s      | 11.46 s       | 0.46×   |
| Codex   | `just clippy`          | `codex-core` | 24.04 s     | 23.31 s       | 1.03×   |
| Codex   | `just test`            | `codex-core` | 32.96 s     | 39.80 s       | 0.83×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-22 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 11.12 s     | 1.44 s        | 7.72×   |
| uv      | `cargo clippy`         | `uv-normalize`       | 15.91 s     | 1.74 s        | 9.16×   |
| uv      | `cargo test --test it` | `uv-normalize`       | 25.60 s     | 4.02 s        | 6.36×   |
| Codex   | `cargo check`          | `codex-utils-string` | 20.75 s     | 7.32 s        | 2.83×   |
| Codex   | `just clippy`          | `codex-utils-string` | 48.72 s     | 7.65 s        | 6.37×   |
| Codex   | `just test`            | `codex-utils-string` | 60.97 s     | 11.94 s       | 5.10×   |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 73.21 s     | 15.48 s | 4.73×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 9.13 s      | 0.78 s  | 11.71×  |
| Codex   | Check after build        | `codex-core`         | 126.06 s    | 35.67 s | 3.53×   |
| Codex   | No-op formatting         | Workspace            | 12.71 s     | 0.20 s  | 63.93×  |
| Codex   | Formatting after an edit | `codex-core`         | 12.78 s     | 0.35 s  | 36.86×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.26 s      | 0.74 s  | 4.42×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 116.30 s    | 65.34 s | 1.78×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 118.42 s    | 11.90 s | 9.95×   |

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
