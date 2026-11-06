# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.99.0-26 to upstream Rust, end-to-end development is around 1.79× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 405.17 s    | 223.90 s | 44.74%     |
| uv session                                 | 135.03 s    | 76.92 s  | 43.03%     |
| Codex session                              | 359.80 s    | 187.38 s | 47.92%     |
| ty session                                 | 199.38 s    | 127.31 s | 36.14%     |
| All sessions                               | 1,099.38 s  | 615.51 s | 44.01%     |
| `cargo check`                              | 100.21 s    | 36.35 s  | 63.73%     |
| `cargo test`, `cargo nextest`, `just test` | 645.98 s    | 429.97 s | 33.44%     |
| `cargo clippy`                             | 318.57 s    | 118.59 s | 62.78%     |
| `cargo fmt`                                | 13.82 s     | 8.49 s   | 38.57%     |
| Other commands                             | 19.31 s     | 20.15 s  | −4.39%     |
| All commands                               | 1,097.89 s  | 613.55 s | 44.12%     |

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
testing, and refining the ideas explored in this project; good ideas can then be proven out and
ultimately proposed upstream.

For an explanation of the major optimizations and their measured impact, see
[Optimizations](docs/optimizations.md).

Ohm's patches are maintained in the following repositories:

- [`ohm-rust`](https://github.com/astral-sh/ohm-rust): Rust compiler and standard library.
- [`ohm-cargo`](https://github.com/astral-sh/ohm-cargo): Cargo.
- [`ohm-rust-clippy`](https://github.com/astral-sh/ohm-rust-clippy): Clippy.
- [`ohm-rustfmt`](https://github.com/astral-sh/ohm-rustfmt): rustfmt.

## Benchmarks

See the [benchmark guide](BENCHMARKS.md) for details.

<!-- benchmark:developer-workflows -->

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-26 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.77 s     | 12.07 s       | 12.34%     |
| Ruff/ty | Edit dependency → downstream test | 13.87 s     | 11.86 s       | 14.51%     |
| Ruff/ty | Edit → check → test → check       | 20.41 s     | 19.12 s       | 6.32%      |
| Ruff/ty | Check → build → check             | 74.30 s     | 49.57 s       | 33.28%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.27 s     | 20.37 s       | 22.48%     |
| uv      | Edit → focused test               | 17.47 s     | 8.57 s        | 50.94%     |
| uv      | Edit dependency → downstream test | 20.93 s     | 2.32 s        | 88.93%     |
| uv      | Edit → check → test → check       | 20.79 s     | 10.89 s       | 47.60%     |
| uv      | Check → build → check             | 112.83 s    | 59.07 s       | 47.65%     |
| uv      | Edit → fmt → clippy → test        | 23.56 s     | 12.40 s       | 47.40%     |
| Codex   | Edit → focused test               | 18.67 s     | 17.32 s       | 7.26%      |
| Codex   | Edit dependency → downstream test | 37.19 s     | 2.23 s        | 94.00%     |
| Codex   | Edit → check → test → check       | 23.63 s     | 22.48 s       | 4.85%      |
| Codex   | Check → build → check             | 111.74 s    | 72.19 s       | 35.40%     |
| Codex   | Edit → fmt → clippy → test        | 26.34 s     | 21.56 s       | 18.13%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-26 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 1.92 s      | 1.70 s        | 1.13×   |
| uv      | `cargo clippy`         | `uv`         | 3.15 s      | 2.43 s        | 1.29×   |
| uv      | `cargo test --test it` | `uv`         | 16.93 s     | 7.93 s        | 2.14×   |
| Codex   | `cargo check`          | `codex-core` | 2.77 s      | 2.56 s        | 1.08×   |
| Codex   | `just clippy`          | `codex-core` | 13.71 s     | 8.87 s        | 1.55×   |
| Codex   | `just test`            | `codex-core` | 18.35 s     | 17.97 s       | 1.02×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-26 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 8.81 s      | 0.45 s        | 19.68×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.43 s     | 0.53 s        | 23.27×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.64 s     | 2.16 s        | 9.07×   |
| Codex   | `cargo check`          | `codex-utils-string` | 11.64 s     | 0.45 s        | 25.82×  |
| Codex   | `just clippy`          | `codex-utils-string` | 27.77 s     | 0.60 s        | 45.98×  |
| Codex   | `just test`            | `codex-utils-string` | 36.03 s     | 1.78 s        | 20.21×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 58.72 s     | 13.02 s | 4.51×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.54 s      | 0.64 s  | 10.30×  |
| Codex   | Check after build        | `codex-core`         | 72.67 s     | 20.02 s | 3.63×   |
| Codex   | No-op formatting         | Workspace            | 6.72 s      | 0.08 s  | 85.99×  |
| Codex   | Formatting after an edit | `codex-core`         | 6.52 s      | 0.13 s  | 50.58×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 1.66 s      | 0.54 s  | 3.10×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 65.29 s     | 38.27 s | 1.71×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 65.22 s     | 37.85 s | 1.72×   |
| Ruff    | Doctests                 | Selected crates      | 13.600 s    | 1.628 s | 8.35×   |

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
