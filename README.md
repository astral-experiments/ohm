# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-2 to upstream Rust, end-to-end development is around 1.87× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 391.42 s     | 213.33 s | 45.50%     |
| uv session                                 | 131.17 s     | 71.19 s  | 45.73%     |
| Codex session                              | 500.53 s     | 252.70 s | 49.51%     |
| ty session                                 | 291.26 s     | 164.14 s | 43.64%     |
| All sessions                               | 1,314.39 s   | 701.36 s | 46.64%     |
| `cargo check`                              | 144.51 s     | 44.92 s  | 68.92%     |
| `cargo test`, `cargo nextest`, `just test` | 774.16 s     | 485.07 s | 37.34%     |
| `cargo clippy`                             | 349.28 s     | 142.08 s | 59.32%     |
| `cargo fmt`                                | 13.84 s      | 8.83 s   | 36.22%     |
| Other commands                             | 29.91 s      | 17.70 s  | 40.83%     |
| All commands                               | 1,311.70 s   | 698.60 s | 46.74%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-2/install.sh | sh
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
For example, `cargo +ohm-1.100.0-2 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-2 | Time saved |
| ------- | --------------------------------- | ------------ | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 15.14 s      | 13.70 s       | 9.46%      |
| Ruff/ty | Edit dependency → downstream test | 13.40 s      | 11.02 s       | 17.80%     |
| Ruff/ty | Edit → check → test → check       | 21.58 s      | 20.65 s       | 4.30%      |
| Ruff/ty | Check → build → check             | 78.64 s      | 50.86 s       | 35.33%     |
| Ruff/ty | Edit → fmt → clippy → test        | 25.11 s      | 21.06 s       | 16.12%     |
| uv      | Edit → focused test               | 17.11 s      | 7.17 s        | 58.10%     |
| uv      | Edit dependency → downstream test | 18.81 s      | 2.36 s        | 87.47%     |
| uv      | Edit → check → test → check       | 19.54 s      | 9.56 s        | 51.07%     |
| uv      | Check → build → check             | 110.42 s     | 54.80 s       | 50.37%     |
| uv      | Edit → fmt → clippy → test        | 21.27 s      | 10.60 s       | 50.16%     |
| Codex   | Edit → focused test               | 27.87 s      | 24.46 s       | 12.24%     |
| Codex   | Edit dependency → downstream test | 52.55 s      | 3.96 s        | 92.47%     |
| Codex   | Edit → check → test → check       | 33.68 s      | 29.55 s       | 12.26%     |
| Codex   | Check → build → check             | 163.53 s     | 98.90 s       | 39.52%     |
| Codex   | Edit → fmt → clippy → test        | 38.85 s      | 28.08 s       | 27.71%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-2 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.09 s       | 1.80 s        | 1.16×   |
| uv      | `cargo clippy`         | `uv`         | 3.07 s       | 2.29 s        | 1.34×   |
| uv      | `cargo test --test it` | `uv`         | 17.47 s      | 6.91 s        | 2.53×   |
| Codex   | `cargo check`          | `codex-core` | 5.46 s       | 4.92 s        | 1.11×   |
| Codex   | `just clippy`          | `codex-core` | 18.70 s      | 13.94 s       | 1.34×   |
| Codex   | `just test`            | `codex-core` | 32.73 s      | 25.54 s       | 1.28×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-2 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.50 s       | 0.46 s        | 20.62×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.75 s      | 0.57 s        | 22.22×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 18.95 s      | 2.15 s        | 8.81×   |
| Codex   | `cargo check`          | `codex-utils-string` | 21.07 s      | 0.94 s        | 22.32×  |
| Codex   | `just clippy`          | `codex-utils-string` | 43.44 s      | 1.23 s        | 35.40×  |
| Codex   | `just test`            | `codex-utils-string` | 50.10 s      | 3.37 s        | 14.87×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 56.23 s      | 11.03 s | 5.10×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.83 s       | 0.55 s  | 12.43×  |
| Codex   | Check after build        | `codex-core`         | 131.22 s     | 36.47 s | 3.60×   |
| Codex   | No-op formatting         | Workspace            | 10.25 s      | 0.21 s  | 49.01×  |
| Codex   | Formatting after an edit | `codex-core`         | 10.31 s      | 0.37 s  | 27.96×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.46 s       | 0.73 s  | 4.72×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 95.29 s      | 57.45 s | 1.66×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 98.97 s      | 62.55 s | 1.58×   |
| Ruff    | Doctests                 | Selected crates      | 14.587 s     | 1.661 s | 8.78×   |

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
