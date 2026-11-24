# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-9 to upstream Rust, end-to-end development is around 2.25× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 430.67 s     | 179.92 s | 58.22%     |
| uv session                                 | 147.55 s     | 75.21 s  | 49.03%     |
| Codex session                              | 563.93 s     | 235.28 s | 58.28%     |
| ty session                                 | 295.18 s     | 149.34 s | 49.41%     |
| All sessions                               | 1,437.33 s   | 639.75 s | 55.49%     |
| `cargo check`                              | 153.78 s     | 46.29 s  | 69.90%     |
| `cargo test`, `cargo nextest`, `just test` | 845.94 s     | 442.20 s | 47.73%     |
| `cargo clippy`                             | 387.86 s     | 123.94 s | 68.04%     |
| `cargo fmt`                                | 15.11 s      | 9.33 s   | 38.26%     |
| Other commands                             | 31.52 s      | 14.89 s  | 52.75%     |
| All commands                               | 1,434.22 s   | 636.65 s | 55.61%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-9/install.sh | sh
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
For example, `cargo +ohm-1.100.0-9 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-9 | Time saved |
| ------- | --------------------------------- | ------------ | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.53 s      | 12.50 s       | 7.58%      |
| Ruff/ty | Edit dependency → downstream test | 8.58 s       | 6.20 s        | 27.71%     |
| Ruff/ty | Edit → check → test → check       | 13.78 s      | 11.17 s       | 18.97%     |
| Ruff/ty | Check → build → check             | 53.93 s      | 32.32 s       | 40.06%     |
| Ruff/ty | Edit → fmt → clippy → test        | 16.83 s      | 11.84 s       | 29.67%     |
| uv      | Edit → focused test               | 20.46 s      | 7.91 s        | 61.33%     |
| uv      | Edit dependency → downstream test | 22.16 s      | 2.31 s        | 89.59%     |
| uv      | Edit → check → test → check       | 24.22 s      | 10.18 s       | 57.97%     |
| uv      | Check → build → check             | 79.44 s      | 36.59 s       | 53.94%     |
| uv      | Edit → fmt → clippy → test        | 16.07 s      | 7.28 s        | 54.70%     |
| Codex   | Edit → focused test               | 17.81 s      | 10.53 s       | 40.90%     |
| Codex   | Edit dependency → downstream test | 45.53 s      | 3.82 s        | 91.61%     |
| Codex   | Edit → check → test → check       | 32.48 s      | 20.70 s       | 36.27%     |
| Codex   | Check → build → check             | 178.47 s     | 102.51 s      | 42.56%     |
| Codex   | Edit → fmt → clippy → test        | 22.30 s      | 13.09 s       | 41.29%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-9 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.44 s       | 1.87 s        | 1.31×   |
| uv      | `cargo clippy`         | `uv`         | 3.51 s       | 2.54 s        | 1.38×   |
| uv      | `cargo test --test it` | `uv`         | 21.40 s      | 8.37 s        | 2.56×   |
| Codex   | `cargo check`          | `codex-core` | 2.96 s       | 2.33 s        | 1.27×   |
| Codex   | `just clippy`          | `codex-core` | 11.31 s      | 8.40 s        | 1.35×   |
| Codex   | `just test`            | `codex-core` | 16.88 s      | 11.32 s       | 1.49×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-9 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 10.36 s      | 0.58 s        | 17.92×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 14.26 s      | 0.66 s        | 21.74×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 21.26 s      | 2.05 s        | 10.35×  |
| Codex   | `cargo check`          | `codex-utils-string` | 11.55 s      | 0.42 s        | 27.74×  |
| Codex   | `just clippy`          | `codex-utils-string` | 22.91 s      | 0.54 s        | 42.27×  |
| Codex   | `just test`            | `codex-utils-string` | 30.79 s      | 1.64 s        | 18.73×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 63.89 s      | 11.86 s | 5.39×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 8.04 s       | 0.56 s  | 14.35×  |
| Codex   | Check after build        | `codex-core`         | 72.87 s      | 17.70 s | 4.12×   |
| Codex   | No-op formatting         | Workspace            | 7.11 s       | 0.09 s  | 82.14×  |
| Codex   | Formatting after an edit | `codex-core`         | 7.01 s       | 0.14 s  | 51.41×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 1.83 s       | 0.29 s  | 6.29×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 100.85 s     | 50.74 s | 1.99×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 107.88 s     | 54.06 s | 2.00×   |
| Ruff    | Doctests                 | Selected crates      | 15.654 s     | 1.685 s | 9.29×   |

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
