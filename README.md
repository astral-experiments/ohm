# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-13 to upstream Rust, end-to-end development is around 2.28× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 423.08 s     | 177.40 s | 58.07%     |
| uv session                                 | 144.86 s     | 66.09 s  | 54.38%     |
| Codex session                              | 540.27 s     | 227.19 s | 57.95%     |
| ty session                                 | 290.51 s     | 143.86 s | 50.48%     |
| All sessions                               | 1,398.72 s   | 614.54 s | 56.06%     |
| `cargo check`                              | 152.72 s     | 45.88 s  | 69.96%     |
| `cargo test`, `cargo nextest`, `just test` | 835.17 s     | 420.85 s | 49.61%     |
| `cargo clippy`                             | 363.98 s     | 125.68 s | 65.47%     |
| `cargo fmt`                                | 14.62 s      | 4.28 s   | 70.75%     |
| Other commands                             | 29.22 s      | 14.70 s  | 49.68%     |
| All commands                               | 1,395.70 s   | 611.39 s | 56.19%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-13/install.sh | sh
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
For example, `cargo +ohm-1.100.0-13 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-13 | Time saved |
| ------- | --------------------------------- | ------------ | -------------- | ---------- |
| Ruff/ty | Edit → focused test               | 14.93 s      | 11.46 s        | 23.22%     |
| Ruff/ty | Edit dependency → downstream test | 15.67 s      | 10.17 s        | 35.14%     |
| Ruff/ty | Edit → check → test → check       | 24.14 s      | 17.93 s        | 25.73%     |
| Ruff/ty | Check → build → check             | 81.41 s      | 49.66 s        | 39.00%     |
| Ruff/ty | Edit → fmt → clippy → test        | 28.38 s      | 18.32 s        | 35.45%     |
| uv      | Edit → focused test               | 13.35 s      | 4.53 s         | 66.09%     |
| uv      | Edit dependency → downstream test | 13.64 s      | 1.37 s         | 89.99%     |
| uv      | Edit → check → test → check       | 14.86 s      | 5.73 s         | 61.42%     |
| uv      | Check → build → check             | 80.29 s      | 35.48 s        | 55.81%     |
| uv      | Edit → fmt → clippy → test        | 16.34 s      | 6.51 s         | 60.14%     |
| Codex   | Edit → focused test               | 30.53 s      | 19.58 s        | 35.88%     |
| Codex   | Edit dependency → downstream test | 54.84 s      | 3.47 s         | 93.68%     |
| Codex   | Edit → check → test → check       | 41.83 s      | 19.89 s        | 52.44%     |
| Codex   | Check → build → check             | 110.47 s     | 62.15 s        | 43.75%     |
| Codex   | Edit → fmt → clippy → test        | 23.09 s      | 13.39 s        | 41.99%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-13 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | -------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.33 s       | 1.47 s         | 1.58×   |
| uv      | `cargo clippy`         | `uv`         | 2.96 s       | 2.07 s         | 1.43×   |
| uv      | `cargo test --test it` | `uv`         | 17.96 s      | 6.59 s         | 2.72×   |
| Codex   | `cargo check`          | `codex-core` | 3.00 s       | 2.25 s         | 1.33×   |
| Codex   | `just clippy`          | `codex-core` | 12.11 s      | 8.83 s         | 1.37×   |
| Codex   | `just test`            | `codex-core` | 17.62 s      | 11.12 s        | 1.58×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-13 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | -------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.45 s       | 0.46 s         | 20.55×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.79 s      | 0.59 s         | 21.85×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.24 s      | 2.14 s         | 8.97×   |
| Codex   | `cargo check`          | `codex-utils-string` | 12.59 s      | 0.44 s         | 28.74×  |
| Codex   | `just clippy`          | `codex-utils-string` | 24.96 s      | 0.55 s         | 45.38×  |
| Codex   | `just test`            | `codex-utils-string` | 31.75 s      | 1.74 s         | 18.29×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 56.06 s      | 9.79 s  | 5.73×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.82 s       | 0.48 s  | 14.18×  |
| Codex   | Check after build        | `codex-core`         | 79.83 s      | 17.69 s | 4.51×   |
| Codex   | No-op formatting         | Workspace            | 7.27 s       | 0.08 s  | 89.82×  |
| Codex   | Formatting after an edit | `codex-core`         | 6.84 s       | 0.12 s  | 57.11×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.01 s       | 0.32 s  | 6.24×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 91.44 s      | 46.76 s | 1.96×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 96.44 s      | 47.54 s | 2.03×   |
| Ruff    | Doctests                 | Selected crates      | 15.533 s     | 1.679 s | 9.25×   |

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
