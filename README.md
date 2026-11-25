# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-11 to upstream Rust, end-to-end development is around 2.24× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 291.50 s     | 122.84 s | 57.86%     |
| uv session                                 | 94.13 s      | 45.28 s  | 51.90%     |
| Codex session                              | 491.74 s     | 210.87 s | 57.12%     |
| ty session                                 | 289.66 s     | 143.05 s | 50.61%     |
| All sessions                               | 1,167.03 s   | 522.04 s | 55.27%     |
| `cargo check`                              | 139.43 s     | 41.26 s  | 70.41%     |
| `cargo test`, `cargo nextest`, `just test` | 680.41 s     | 352.51 s | 48.19%     |
| `cargo clippy`                             | 306.16 s     | 106.15 s | 65.33%     |
| `cargo fmt`                                | 9.80 s       | 5.26 s   | 46.32%     |
| Other commands                             | 28.96 s      | 14.50 s  | 49.94%     |
| All commands                               | 1,164.75 s   | 519.67 s | 55.38%     |

<!-- /benchmark:sessions -->

And disk usage (on APFS) decreases by around 55%:

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

Compared to upstream, Ohm:

- Enables (by default) existing experimental features (e.g., parallel compiler frontends).
- Implements experimental, performance-oriented features proposed upstream (e.g.,
  [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790)).
- Fixes various performance bugs and regressions (e.g., around `target/` size increases).
- Implements additional optimizations identified by Codex (e.g., reusing build artifacts between
  `cargo build` and `cargo check`, avoiding rustfmt on unchanged files).

**Warning:** Ohm includes backported and experimental Rust, Cargo, and Clippy optimizations that may
be unsound. This README is human-edited, but all code changes, PR summaries, and additional
documentation were authored entirely by GPT in Codex.

## Installation

Ohm supports Apple Silicon macOS and x86_64 Linux. Install [rustup](https://rustup.rs/), then
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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-11/install.sh | sh
```

Each Ohm release targets a specific upstream Rust release. When a Rust version becomes available,
we replay the optimizations that remain relevant and drop those that have already landed upstream.
Multiple Ohm revisions may target the same Rust release; for example, `ohm-1.97.1-20` and
`ohm-1.97.1-21`.

## Usage

Use rustup's `+toolchain` syntax to select Ohm:

```console
cargo +ohm test
cargo +ohm check
cargo +ohm clippy
cargo +ohm fmt
```

Exact toolchain names have the form `ohm-<rust-version>-<ohm-revision>`.
For example, `cargo +ohm-1.100.0-11 test` selects that installed revision.

Ohm enables dependency-aware rebuild reduction, cached relinking, parallel compiler frontends,
and reuse of previously built registry and workspace dependencies by default.
Opt out with `-Zohm-defaults=no`:

```console
cargo +ohm -Zohm-defaults=no test
```

Run Ohm's garbage collector from any directory to clean up unused build artifacts in idle worktrees
and shared caches.

```console
cargo +ohm gc
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

## Philosophy

Rust's compile times and disk usage are emerging as bottlenecks in day-to-day development,
especially as agents enable us to parallelize across (dozens of) worktrees.

Ohm enables experimental optimizations to improve Rust's iteration speed and throughput. This is a
deliberate tradeoff: we accept the risks of experimental implementations in local development, where
the blast radius of bugs is comparatively limited and the benefits of faster iteration are
substantial (while continuing to use the official toolchain for production builds).

Ohm is authored entirely by the GPT model series in Codex. Agents lower the cost of implementing,
testing, and refining ideas. When an optimization proves useful, we can propose it upstream. To
keep that path open, Ohm avoids _fundamental_ changes to the Rust toolchain, such as introducing a
stateful development server.

For details on the optimizations Ohm enables and their measured impact, see
[Optimizations](docs/optimizations.md).

Ohm's patches are maintained in the following repositories:

- [`ohm-rust`](https://github.com/astral-sh/ohm-rust): Rust compiler and standard library.
- [`ohm-cargo`](https://github.com/astral-sh/ohm-cargo): Cargo.
- [`ohm-rust-clippy`](https://github.com/astral-sh/ohm-rust-clippy): Clippy.
- [`ohm-rustfmt`](https://github.com/astral-sh/ohm-rustfmt): rustfmt.

## Benchmarks

See the [benchmark guide](BENCHMARKS.md) for details.

<!-- benchmark:developer-workflows -->

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-11 | Time saved |
| ------- | --------------------------------- | ------------ | -------------- | ---------- |
| Ruff/ty | Edit → focused test               | 9.74 s       | 7.76 s         | 20.39%     |
| Ruff/ty | Edit dependency → downstream test | 14.49 s      | 10.13 s        | 30.08%     |
| Ruff/ty | Edit → check → test → check       | 20.47 s      | 18.45 s        | 9.85%      |
| Ruff/ty | Check → build → check             | 81.36 s      | 44.27 s        | 45.59%     |
| Ruff/ty | Edit → fmt → clippy → test        | 27.73 s      | 16.54 s        | 40.35%     |
| uv      | Edit → focused test               | 21.19 s      | 9.81 s         | 53.69%     |
| uv      | Edit dependency → downstream test | 24.20 s      | 2.82 s         | 88.35%     |
| uv      | Edit → check → test → check       | 26.23 s      | 11.03 s        | 57.96%     |
| uv      | Check → build → check             | 79.49 s      | 36.25 s        | 54.39%     |
| uv      | Edit → fmt → clippy → test        | 15.80 s      | 6.81 s         | 56.88%     |
| Codex   | Edit → focused test               | 17.92 s      | 10.46 s        | 41.65%     |
| Codex   | Edit dependency → downstream test | 52.30 s      | 4.39 s         | 91.61%     |
| Codex   | Edit → check → test → check       | 39.76 s      | 24.87 s        | 37.44%     |
| Codex   | Check → build → check             | 112.65 s     | 63.34 s        | 43.78%     |
| Codex   | Edit → fmt → clippy → test        | 35.82 s      | 18.91 s        | 47.20%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-11 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | -------------- | ------- |
| uv      | `cargo check`          | `uv`         | 1.35 s       | 1.01 s         | 1.34×   |
| uv      | `cargo clippy`         | `uv`         | 2.00 s       | 1.39 s         | 1.44×   |
| uv      | `cargo test --test it` | `uv`         | 12.45 s      | 4.46 s         | 2.79×   |
| Codex   | `cargo check`          | `codex-core` | 4.30 s       | 3.42 s         | 1.26×   |
| Codex   | `just clippy`          | `codex-core` | 17.16 s      | 12.63 s        | 1.36×   |
| Codex   | `just test`            | `codex-core` | 25.35 s      | 16.66 s        | 1.52×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-11 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | -------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 5.97 s       | 0.24 s         | 24.75×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 8.29 s       | 0.32 s         | 25.85×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 12.40 s      | 2.31 s         | 5.36×   |
| Codex   | `cargo check`          | `codex-utils-string` | 17.15 s      | 0.81 s         | 21.10×  |
| Codex   | `just clippy`          | `codex-utils-string` | 33.41 s      | 1.10 s         | 30.31×  |
| Codex   | `just test`            | `codex-utils-string` | 47.79 s      | 3.17 s         | 15.09×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 40.70 s      | 6.19 s  | 6.57×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 4.49 s       | 0.27 s  | 16.41×  |
| Codex   | Check after build        | `codex-core`         | 103.52 s     | 26.41 s | 3.92×   |
| Codex   | No-op formatting         | Workspace            | 9.88 s       | 0.21 s  | 46.07×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.60 s       | 0.28 s  | 34.18×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.61 s       | 0.80 s  | 3.25×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 95.72 s      | 48.81 s | 1.96×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 114.03 s     | 52.81 s | 2.16×   |
| Ruff    | Doctests                 | Selected crates      | 9.671 s      | 1.138 s | 8.50×   |

<!-- /benchmark:features -->

## License

Ohm is licensed under either of

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
  <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>)

at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in Ohm
by you, as defined in the Apache-2.0 license, shall be dually licensed as above, without any
additional terms or conditions.
