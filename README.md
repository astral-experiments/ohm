# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An experimental fork of the Rust toolchain, designed for fast, highly parallel local development.

Comparing Ohm 1.100.0-5 to upstream Rust, end-to-end development is around 2.06× faster:

<!-- benchmark:sessions -->

| Scope                                      | Rust 1.100.0 | Ohm      | Time saved |
| ------------------------------------------ | ------------ | -------- | ---------- |
| Ruff session                               | 417.60 s     | 187.43 s | 55.12%     |
| uv session                                 | 140.05 s     | 73.57 s  | 47.47%     |
| Codex session                              | 569.88 s     | 265.57 s | 53.40%     |
| ty session                                 | 287.84 s     | 159.31 s | 44.65%     |
| All sessions                               | 1,415.37 s   | 685.88 s | 51.54%     |
| `cargo check`                              | 164.31 s     | 49.77 s  | 69.71%     |
| `cargo test`, `cargo nextest`, `just test` | 840.60 s     | 467.93 s | 44.33%     |
| `cargo clippy`                             | 364.47 s     | 140.01 s | 61.58%     |
| `cargo fmt`                                | 14.56 s      | 8.93 s   | 38.68%     |
| Other commands                             | 28.34 s      | 16.22 s  | 42.75%     |
| All commands                               | 1,412.29 s   | 682.87 s | 51.65%     |

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
  https://labs.astral.sh/ohm/releases/ohm-1.100.0-5/install.sh | sh
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
For example, `cargo +ohm-1.100.0-5 test` selects that installed revision.

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

| Project | Workflow                          | Rust 1.100.0 | Ohm 1.100.0-5 | Time saved |
| ------- | --------------------------------- | ------------ | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 15.40 s      | 12.53 s       | 18.64%     |
| Ruff/ty | Edit dependency → downstream test | 13.99 s      | 11.40 s       | 18.50%     |
| Ruff/ty | Edit → check → test → check       | 22.02 s      | 19.45 s       | 11.67%     |
| Ruff/ty | Check → build → check             | 81.69 s      | 54.70 s       | 33.04%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.65 s      | 22.67 s       | 14.92%     |
| uv      | Edit → focused test               | 21.42 s      | 7.60 s        | 64.50%     |
| uv      | Edit dependency → downstream test | 21.39 s      | 2.43 s        | 88.64%     |
| uv      | Edit → check → test → check       | 24.52 s      | 11.19 s       | 54.34%     |
| uv      | Check → build → check             | 78.77 s      | 38.12 s       | 51.60%     |
| uv      | Edit → fmt → clippy → test        | 16.05 s      | 7.17 s        | 55.32%     |
| Codex   | Edit → focused test               | 34.68 s      | 20.62 s       | 40.55%     |
| Codex   | Edit dependency → downstream test | 52.97 s      | 4.34 s        | 91.80%     |
| Codex   | Edit → check → test → check       | 34.10 s      | 26.22 s       | 23.11%     |
| Codex   | Check → build → check             | 179.07 s     | 112.34 s      | 37.26%     |
| Codex   | Edit → fmt → clippy → test        | 40.79 s      | 29.77 s       | 27.02%     |

<!-- /benchmark:developer-workflows -->

**Direct edits** modify the crate being checked, linted, or tested:

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.100.0 | Ohm 1.100.0-5 | Speedup |
| ------- | ---------------------- | ------------ | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 2.00 s       | 1.72 s        | 1.16×   |
| uv      | `cargo clippy`         | `uv`         | 3.16 s       | 2.50 s        | 1.27×   |
| uv      | `cargo test --test it` | `uv`         | 16.31 s      | 6.97 s        | 2.34×   |
| Codex   | `cargo check`          | `codex-core` | 5.23 s       | 4.39 s        | 1.19×   |
| Codex   | `just clippy`          | `codex-core` | 19.13 s      | 15.85 s       | 1.21×   |
| Codex   | `just test`            | `codex-core` | 29.61 s      | 20.97 s       | 1.41×   |

<!-- /benchmark:direct -->

**Indirect edits** modify a dependency's implementation without changing its public API, so Ohm can
avoid rebuilding unchanged dependents:

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.100.0 | Ohm 1.100.0-5 | Speedup |
| ------- | ---------------------- | -------------------- | ------------ | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 8.98 s       | 0.47 s        | 18.99×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 13.02 s      | 0.65 s        | 19.96×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 18.35 s      | 2.05 s        | 8.93×   |
| Codex   | `cargo check`          | `codex-utils-string` | 19.40 s      | 0.96 s        | 20.30×  |
| Codex   | `just clippy`          | `codex-utils-string` | 36.69 s      | 1.41 s        | 25.99×  |
| Codex   | `just test`            | `codex-utils-string` | 56.68 s      | 3.93 s        | 14.43×  |

<!-- /benchmark:dependency -->

**Other common cases** include build-to-check reuse, formatting, and worktree startup:

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.100.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ------------ | ------- | ------- |
| uv      | Check after build        | `uv`                 | 57.06 s      | 12.11 s | 4.71×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 7.20 s       | 0.50 s  | 14.42×  |
| Codex   | Check after build        | `codex-core`         | 111.35 s     | 37.72 s | 2.95×   |
| Codex   | No-op formatting         | Workspace            | 10.17 s      | 0.20 s  | 51.05×  |
| Codex   | Formatting after an edit | `codex-core`         | 10.23 s      | 0.36 s  | 28.21×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 3.73 s       | 0.61 s  | 6.09×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 99.53 s      | 53.44 s | 1.86×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 100.84 s     | 58.77 s | 1.72×   |
| Ruff    | Doctests                 | Selected crates      | 16.280 s     | 2.163 s | 7.53×   |

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
