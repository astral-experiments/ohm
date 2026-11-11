# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.99.0-31 to upstream Rust, end-to-end development is around 1.82× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 419.44 s    | 222.89 s | 46.86%     |
| uv session                                 | 143.05 s    | 76.90 s  | 46.24%     |
| Codex session                              | 496.10 s    | 260.09 s | 47.57%     |
| ty session                                 | 305.32 s    | 188.06 s | 38.41%     |
| All sessions                               | 1,363.91 s  | 747.93 s | 45.16%     |
| `cargo check`                              | 136.96 s    | 44.19 s  | 67.73%     |
| `cargo test`, `cargo nextest`, `just test` | 777.15 s    | 517.92 s | 33.36%     |
| `cargo clippy`                             | 402.55 s    | 144.07 s | 64.21%     |
| `cargo fmt`                                | 14.68 s     | 8.79 s   | 40.12%     |
| Other commands                             | 30.15 s     | 29.92 s  | 0.78%      |
| All commands                               | 1,361.49 s  | 744.89 s | 45.29%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.99.0-9/install.sh | sh
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
For example, `cargo +ohm-1.99.0-9 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-31 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.82 s     | 13.56 s       | 1.91%      |
| Ruff/ty | Edit dependency → downstream test | 13.46 s     | 12.04 s       | 10.53%     |
| Ruff/ty | Edit → check → test → check       | 20.44 s     | 19.47 s       | 4.76%      |
| Ruff/ty | Check → build → check             | 75.32 s     | 49.05 s       | 34.88%     |
| Ruff/ty | Edit → fmt → clippy → test        | 27.59 s     | 22.72 s       | 17.62%     |
| uv      | Edit → focused test               | 16.34 s     | 7.97 s        | 51.20%     |
| uv      | Edit dependency → downstream test | 19.05 s     | 2.57 s        | 86.50%     |
| uv      | Edit → check → test → check       | 20.36 s     | 10.39 s       | 48.98%     |
| uv      | Check → build → check             | 113.86 s    | 61.07 s       | 46.36%     |
| uv      | Edit → fmt → clippy → test        | 21.45 s     | 12.37 s       | 42.33%     |
| Codex   | Edit → focused test               | 27.13 s     | 25.40 s       | 6.37%      |
| Codex   | Edit dependency → downstream test | 52.57 s     | 3.52 s        | 93.30%     |
| Codex   | Edit → check → test → check       | 33.96 s     | 31.35 s       | 7.70%      |
| Codex   | Check → build → check             | 155.69 s    | 102.41 s      | 34.22%     |
| Codex   | Edit → fmt → clippy → test        | 38.07 s     | 31.78 s       | 16.51%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-31 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.21 s      | 1.90 s        | 1.16×   |
| uv      | `cargo clippy`         | `uv`         | 3.40 s      | 2.51 s        | 1.35×   |
| uv      | `cargo test --test it` | `uv`         | 17.31 s     | 8.47 s        | 2.04×   |
| Codex   | `cargo check`          | `codex-core` | 4.31 s      | 3.82 s        | 1.13×   |
| Codex   | `just clippy`          | `codex-core` | 19.94 s     | 13.02 s       | 1.53×   |
| Codex   | `just test`            | `codex-core` | 26.69 s     | 25.70 s       | 1.04×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-31 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.78 s      | 0.54 s        | 18.08×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 13.77 s     | 0.68 s        | 20.20×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.51 s     | 2.34 s        | 8.35×   |
| Codex   | `cargo check`          | `codex-utils-string` | 18.08 s     | 0.84 s        | 21.60×  |
| Codex   | `just clippy`          | `codex-utils-string` | 40.23 s     | 1.30 s        | 30.83×  |
| Codex   | `just test`            | `codex-utils-string` | 50.55 s     | 3.18 s        | 15.89×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 63.88 s     | 13.67 s | 4.67×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 7.64 s      | 0.70 s  | 10.98×  |
| Codex   | Check after build        | `codex-core`         | 102.36 s    | 26.75 s | 3.83×   |
| Codex   | No-op formatting         | Workspace            | 9.73 s      | 0.18 s  | 53.14×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.79 s      | 0.32 s  | 30.84×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.61 s      | 0.62 s  | 4.21×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 94.32 s     | 52.78 s | 1.79×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 112.61 s    | 53.66 s | 2.10×   |
| Ruff    | Doctests                 | Selected crates      | 14.485 s    | 1.657 s | 8.74×   |

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
