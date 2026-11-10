# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.99.0-30 to upstream Rust, end-to-end development is around 1.80× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 415.97 s    | 224.31 s | 46.08%     |
| uv session                                 | 136.16 s    | 75.27 s  | 44.72%     |
| Codex session                              | 496.06 s    | 253.20 s | 48.96%     |
| ty session                                 | 276.09 s    | 181.81 s | 34.15%     |
| All sessions                               | 1,324.28 s  | 734.58 s | 44.53%     |
| `cargo check`                              | 139.18 s    | 43.72 s  | 68.59%     |
| `cargo test`, `cargo nextest`, `just test` | 752.17 s    | 509.26 s | 32.29%     |
| `cargo clippy`                             | 388.68 s    | 141.41 s | 63.62%     |
| `cargo fmt`                                | 13.98 s     | 8.69 s   | 37.87%     |
| Other commands                             | 27.76 s     | 28.35 s  | −2.10%     |
| All commands                               | 1,321.78 s  | 731.42 s | 44.66%     |

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

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-30 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.98 s     | 14.60 s       | −4.44%     |
| Ruff/ty | Edit dependency → downstream test | 13.80 s     | 12.51 s       | 9.29%      |
| Ruff/ty | Edit → check → test → check       | 20.62 s     | 21.58 s       | −4.64%     |
| Ruff/ty | Check → build → check             | 76.23 s     | 49.67 s       | 34.85%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.81 s     | 22.62 s       | 15.64%     |
| uv      | Edit → focused test               | 17.27 s     | 8.25 s        | 52.19%     |
| uv      | Edit dependency → downstream test | 19.56 s     | 2.21 s        | 88.71%     |
| uv      | Edit → check → test → check       | 19.97 s     | 11.00 s       | 44.92%     |
| uv      | Check → build → check             | 110.95 s    | 58.05 s       | 47.68%     |
| uv      | Edit → fmt → clippy → test        | 23.10 s     | 12.61 s       | 45.39%     |
| Codex   | Edit → focused test               | 27.38 s     | 25.11 s       | 8.32%      |
| Codex   | Edit dependency → downstream test | 50.65 s     | 3.36 s        | 93.37%     |
| Codex   | Edit → check → test → check       | 32.57 s     | 31.83 s       | 2.26%      |
| Codex   | Check → build → check             | 152.02 s    | 101.70 s      | 33.10%     |
| Codex   | Edit → fmt → clippy → test        | 36.93 s     | 31.46 s       | 14.79%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-30 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.10 s      | 1.73 s        | 1.22×   |
| uv      | `cargo clippy`         | `uv`         | 3.23 s      | 2.51 s        | 1.29×   |
| uv      | `cargo test --test it` | `uv`         | 17.20 s     | 8.12 s        | 2.12×   |
| Codex   | `cargo check`          | `codex-core` | 4.36 s      | 3.82 s        | 1.14×   |
| Codex   | `just clippy`          | `codex-core` | 19.54 s     | 13.00 s       | 1.50×   |
| Codex   | `just test`            | `codex-core` | 25.76 s     | 24.94 s       | 1.03×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-30 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.09 s      | 0.48 s        | 18.86×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.50 s     | 0.58 s        | 21.66×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.40 s     | 2.18 s        | 8.89×   |
| Codex   | `cargo check`          | `codex-utils-string` | 17.68 s     | 0.82 s        | 21.70×  |
| Codex   | `just clippy`          | `codex-utils-string` | 38.94 s     | 1.06 s        | 36.79×  |
| Codex   | `just test`            | `codex-utils-string` | 47.92 s     | 3.02 s        | 15.86×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 60.26 s     | 12.48 s | 4.83×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.93 s      | 0.69 s  | 10.01×  |
| Codex   | Check after build        | `codex-core`         | 104.49 s    | 26.72 s | 3.91×   |
| Codex   | No-op formatting         | Workspace            | 10.07 s     | 0.18 s  | 56.25×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.55 s      | 0.28 s  | 34.09×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.56 s      | 0.64 s  | 4.01×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 87.69 s     | 48.41 s | 1.81×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 88.23 s     | 48.47 s | 1.82×   |
| Ruff    | Doctests                 | Selected crates      | 15.034 s    | 1.271 s | 11.83×  |

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
