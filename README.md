# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-6 to upstream Rust, end-to-end development is around 2.10× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 373.88 s     | 163.80 s | 56.19%     |
| uv session                                 | 144.05 s     | 80.20 s  | 44.33%     |
| Codex session                              | 592.62 s     | 265.74 s | 55.16%     |
| ty session                                 | 303.94 s     | 164.79 s | 45.78%     |
| All sessions                               | 1,414.50 s   | 674.54 s | 52.31%     |
| `cargo check`                              | 163.82 s     | 50.97 s  | 68.89%     |
| `cargo test`, `cargo nextest`, `just test` | 826.86 s     | 456.96 s | 44.73%     |
| `cargo clippy`                             | 375.19 s     | 137.55 s | 63.34%     |
| `cargo fmt`                                | 14.35 s      | 8.91 s   | 37.88%     |
| Other commands                             | 31.18 s      | 16.97 s  | 45.59%     |
| All commands                               | 1,411.40 s   | 671.37 s | 52.43%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-6/install.sh | sh
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
For example, `cargo +ohm-1.100.0-6 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-6 | Time saved |
| ------- | --------------------------------- | ------------ | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.39 s      | 10.76 s       | 19.64%     |
| Ruff/ty | Edit dependency → downstream test | 15.97 s      | 11.46 s       | 28.28%     |
| Ruff/ty | Edit → check → test → check       | 26.51 s      | 19.02 s       | 28.25%     |
| Ruff/ty | Check → build → check             | 87.19 s      | 49.92 s       | 42.75%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.77 s      | 20.44 s       | 23.64%     |
| uv      | Edit → focused test               | 18.46 s      | 7.56 s        | 59.03%     |
| uv      | Edit dependency → downstream test | 20.66 s      | 2.34 s        | 88.65%     |
| uv      | Edit → check → test → check       | 23.18 s      | 10.42 s       | 55.07%     |
| uv      | Check → build → check             | 122.97 s     | 62.10 s       | 49.50%     |
| uv      | Edit → fmt → clippy → test        | 26.04 s      | 12.30 s       | 52.78%     |
| Codex   | Edit → focused test               | 27.43 s      | 19.04 s       | 30.58%     |
| Codex   | Edit dependency → downstream test | 50.03 s      | 3.88 s        | 92.25%     |
| Codex   | Edit → check → test → check       | 35.65 s      | 22.74 s       | 36.21%     |
| Codex   | Check → build → check             | 189.00 s     | 116.18 s      | 38.53%     |
| Codex   | Edit → fmt → clippy → test        | 45.58 s      | 33.35 s       | 26.83%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-6 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.38 s       | 1.90 s        | 1.26×   |
| uv      | `cargo clippy`         | `uv`         | 3.26 s       | 2.40 s        | 1.36×   |
| uv      | `cargo test --test it` | `uv`         | 18.03 s      | 7.19 s        | 2.51×   |
| Codex   | `cargo check`          | `codex-core` | 4.84 s       | 4.28 s        | 1.13×   |
| Codex   | `just clippy`          | `codex-core` | 18.94 s      | 14.72 s       | 1.29×   |
| Codex   | `just test`            | `codex-core` | 30.04 s      | 20.86 s       | 1.44×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-6 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 10.79 s      | 0.56 s        | 19.15×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.94 s      | 0.61 s        | 21.38×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.73 s      | 2.17 s        | 9.07×   |
| Codex   | `cargo check`          | `codex-utils-string` | 19.24 s      | 0.94 s        | 20.55×  |
| Codex   | `just clippy`          | `codex-utils-string` | 35.53 s      | 1.22 s        | 29.01×  |
| Codex   | `just test`            | `codex-utils-string` | 48.44 s      | 3.29 s        | 14.73×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 61.50 s      | 12.75 s | 4.82×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 7.79 s       | 0.56 s  | 13.88×  |
| Codex   | Check after build        | `codex-core`         | 116.45 s     | 32.92 s | 3.54×   |
| Codex   | No-op formatting         | Workspace            | 10.32 s      | 0.26 s  | 40.11×  |
| Codex   | Formatting after an edit | `codex-core`         | 10.03 s      | 0.35 s  | 29.04×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.15 s       | 0.59 s  | 5.31×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 101.63 s     | 54.51 s | 1.86×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 101.68 s     | 58.39 s | 1.74×   |
| Ruff    | Doctests                 | Selected crates      | 14.191 s     | 1.703 s | 8.33×   |

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
