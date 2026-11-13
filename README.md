# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.99.0-32 to upstream Rust, end-to-end development is around 1.85× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 469.23 s    | 237.56 s | 49.37%     |
| uv session                                 | 135.28 s    | 76.00 s  | 43.82%     |
| Codex session                              | 540.08 s    | 278.15 s | 48.50%     |
| ty session                                 | 307.71 s    | 192.40 s | 37.47%     |
| All sessions                               | 1,452.30 s  | 784.10 s | 46.01%     |
| `cargo check`                              | 145.22 s    | 51.80 s  | 64.33%     |
| `cargo test`, `cargo nextest`, `just test` | 821.78 s    | 538.08 s | 34.52%     |
| `cargo clippy`                             | 437.80 s    | 150.83 s | 65.55%     |
| `cargo fmt`                                | 14.63 s     | 9.40 s   | 35.73%     |
| Other commands                             | 30.18 s     | 30.91 s  | −2.41%     |
| All commands                               | 1,449.61 s  | 781.02 s | 46.12%     |

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

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-32 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 18.24 s     | 14.40 s       | 21.08%     |
| Ruff/ty | Edit dependency → downstream test | 14.30 s     | 11.88 s       | 16.92%     |
| Ruff/ty | Edit → check → test → check       | 22.81 s     | 22.11 s       | 3.08%      |
| Ruff/ty | Check → build → check             | 78.09 s     | 53.57 s       | 31.40%     |
| Ruff/ty | Edit → fmt → clippy → test        | 30.42 s     | 23.32 s       | 23.34%     |
| uv      | Edit → focused test               | 16.21 s     | 7.66 s        | 52.74%     |
| uv      | Edit dependency → downstream test | 19.27 s     | 2.60 s        | 86.51%     |
| uv      | Edit → check → test → check       | 19.50 s     | 10.59 s       | 45.67%     |
| uv      | Check → build → check             | 116.49 s    | 60.35 s       | 48.19%     |
| uv      | Edit → fmt → clippy → test        | 22.37 s     | 12.21 s       | 45.40%     |
| Codex   | Edit → focused test               | 29.90 s     | 24.95 s       | 16.55%     |
| Codex   | Edit dependency → downstream test | 54.31 s     | 4.28 s        | 92.12%     |
| Codex   | Edit → check → test → check       | 36.02 s     | 29.11 s       | 19.19%     |
| Codex   | Check → build → check             | 162.84 s    | 105.44 s      | 35.25%     |
| Codex   | Edit → fmt → clippy → test        | 40.87 s     | 30.79 s       | 24.68%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-32 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.20 s      | 1.88 s        | 1.17×   |
| uv      | `cargo clippy`         | `uv`         | 3.37 s      | 2.42 s        | 1.39×   |
| uv      | `cargo test --test it` | `uv`         | 17.43 s     | 7.42 s        | 2.35×   |
| Codex   | `cargo check`          | `codex-core` | 4.57 s      | 4.16 s        | 1.10×   |
| Codex   | `just clippy`          | `codex-core` | 21.43 s     | 13.96 s       | 1.53×   |
| Codex   | `just test`            | `codex-core` | 28.13 s     | 23.85 s       | 1.18×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-32 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.90 s      | 0.53 s        | 18.51×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 13.86 s     | 0.65 s        | 21.20×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.60 s     | 2.32 s        | 8.44×   |
| Codex   | `cargo check`          | `codex-utils-string` | 18.15 s     | 0.84 s        | 21.57×  |
| Codex   | `just clippy`          | `codex-utils-string` | 40.72 s     | 1.34 s        | 30.38×  |
| Codex   | `just test`            | `codex-utils-string` | 57.37 s     | 3.92 s        | 14.64×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 60.45 s     | 12.13 s | 4.98×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.99 s      | 0.61 s  | 11.42×  |
| Codex   | Check after build        | `codex-core`         | 113.91 s    | 32.27 s | 3.53×   |
| Codex   | No-op formatting         | Workspace            | 10.09 s     | 0.19 s  | 52.69×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.62 s      | 0.30 s  | 31.59×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.98 s      | 0.72 s  | 4.13×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 99.47 s     | 53.13 s | 1.87×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 98.11 s     | 58.82 s | 1.67×   |
| Ruff    | Doctests                 | Selected crates      | 16.868 s    | 1.138 s | 14.82×  |

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
