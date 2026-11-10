# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.99.0-29 to upstream Rust, end-to-end development is around 1.77× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.99.0 | Ohm      | Time saved |
| ------------------------------------------ | ----------- | -------- | ---------- |
| Ruff session                               | 419.09 s    | 225.38 s | 46.22%     |
| uv session                                 | 145.60 s    | 77.52 s  | 46.76%     |
| Codex session                              | 504.77 s    | 275.36 s | 45.45%     |
| ty session                                 | 290.40 s    | 187.93 s | 35.28%     |
| All sessions                               | 1,359.85 s  | 766.20 s | 43.66%     |
| `cargo check`                              | 141.42 s    | 42.74 s  | 69.78%     |
| `cargo test`, `cargo nextest`, `just test` | 778.24 s    | 536.89 s | 31.01%     |
| `cargo clippy`                             | 394.07 s    | 144.93 s | 63.22%     |
| `cargo fmt`                                | 14.71 s     | 8.97 s   | 39.01%     |
| Other commands                             | 28.94 s     | 29.62 s  | −2.35%     |
| All commands                               | 1,357.38 s  | 763.14 s | 43.78%     |

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

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-29 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.49 s     | 14.37 s       | −6.56%     |
| Ruff/ty | Edit dependency → downstream test | 13.67 s     | 12.38 s       | 9.41%      |
| Ruff/ty | Edit → check → test → check       | 20.02 s     | 21.23 s       | −6.04%     |
| Ruff/ty | Check → build → check             | 75.08 s     | 49.62 s       | 33.91%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.36 s     | 21.94 s       | 16.74%     |
| uv      | Edit → focused test               | 16.22 s     | 8.76 s        | 45.97%     |
| uv      | Edit dependency → downstream test | 19.14 s     | 2.58 s        | 86.53%     |
| uv      | Edit → check → test → check       | 19.71 s     | 11.27 s       | 42.80%     |
| uv      | Check → build → check             | 111.49 s    | 59.76 s       | 46.40%     |
| uv      | Edit → fmt → clippy → test        | 21.32 s     | 12.16 s       | 42.97%     |
| Codex   | Edit → focused test               | 29.85 s     | 26.56 s       | 11.01%     |
| Codex   | Edit dependency → downstream test | 51.62 s     | 3.49 s        | 93.24%     |
| Codex   | Edit → check → test → check       | 34.86 s     | 30.95 s       | 11.20%     |
| Codex   | Check → build → check             | 165.14 s    | 108.18 s      | 34.49%     |
| Codex   | Edit → fmt → clippy → test        | 40.33 s     | 34.37 s       | 14.78%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-29 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.18 s      | 1.87 s        | 1.16×   |
| uv      | `cargo clippy`         | `uv`         | 3.44 s      | 2.55 s        | 1.35×   |
| uv      | `cargo test --test it` | `uv`         | 17.81 s     | 8.33 s        | 2.14×   |
| Codex   | `cargo check`          | `codex-core` | 4.43 s      | 3.96 s        | 1.12×   |
| Codex   | `just clippy`          | `codex-core` | 20.52 s     | 14.21 s       | 1.44×   |
| Codex   | `just test`            | `codex-core` | 27.34 s     | 25.22 s       | 1.08×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-29 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 9.70 s      | 0.53 s        | 18.13×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 13.67 s     | 0.67 s        | 20.41×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 20.22 s     | 2.39 s        | 8.48×   |
| Codex   | `cargo check`          | `codex-utils-string` | 18.27 s     | 0.86 s        | 21.33×  |
| Codex   | `just clippy`          | `codex-utils-string` | 40.48 s     | 1.30 s        | 31.22×  |
| Codex   | `just test`            | `codex-utils-string` | 51.45 s     | 3.56 s        | 14.47×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 62.80 s     | 12.86 s | 4.88×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 8.30 s      | 1.38 s  | 6.03×   |
| Codex   | Check after build        | `codex-core`         | 104.98 s    | 27.93 s | 3.76×   |
| Codex   | No-op formatting         | Workspace            | 9.13 s      | 0.18 s  | 51.57×  |
| Codex   | Formatting after an edit | `codex-core`         | 9.58 s      | 0.30 s  | 32.05×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 2.82 s      | 0.67 s  | 4.18×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 93.03 s     | 50.89 s | 1.83×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 94.22 s     | 53.82 s | 1.75×   |
| Ruff    | Doctests                 | Selected crates      | 15.409 s    | 1.289 s | 11.95×  |

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
