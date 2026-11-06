# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-26 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-26 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    199.38 s |      127.31 s |     36.14% |
| Worktree startup (ext4)  |     65.29 s |       38.27 s |     41.38% |
| Worktree startup (Btrfs) |     65.22 s |       37.85 s |     41.97% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.18 s |  0.19 s |     -2.76% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.20 s |  0.18 s |     12.25% |                         0 / 0 |
| First failing focused mdtest             | 57.63 s | 42.71 s |     25.90% |                     116 / 116 |
| Repeat after Markdown-only edit          |  0.75 s |  0.70 s |      6.64% |                         0 / 0 |
| Focused mdtest after Rust fix            | 17.84 s | 10.21 s |     42.74% |                         3 / 3 |
| Full semantic package tests              | 52.99 s | 35.04 s |     33.88% |                         2 / 2 |
| Rebuild CLI with its original features   | 17.50 s | 18.45 s |     -5.43% |                         6 / 6 |
| Compare 24 diagnostic results            |  1.41 s |  1.36 s |      3.26% |                         0 / 0 |
| Clippy with all targets and features     | 49.79 s | 17.50 s |     64.86% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 195.87–204.53 s for Rust and 125.41–128.73 s for Ohm. Initial CLI build medians are 79.87 s and 69.24 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   0.40 s |          64.82 s | 65.29 s | 61.67–68.00 s |               304 |                    65.21 s |
| Ohm + shared build                 |   0.46 s |          42.15 s | 42.62 s | 41.46–43.25 s |                80 |                    52.84 s |
| Ohm + shared build + trust opt-ins |   0.46 s |          37.81 s | 38.27 s | 38.16–39.54 s |                36 |                    53.51 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   0.53 s |          64.62 s | 65.22 s | 64.67–67.52 s |               304 |                    66.05 s |
| Ohm + shared build                 |   0.50 s |          41.68 s | 42.24 s | 42.06–43.04 s |                80 |                    51.49 s |
| Ohm + shared build + trust opt-ins |   2.35 s |          35.51 s | 37.85 s | 35.74–40.17 s |                15 |                    50.96 s |

The trusted Btrfs runs seed 2735 files, including 2697 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Rome Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
