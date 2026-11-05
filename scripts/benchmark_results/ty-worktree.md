# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-25 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-25 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    276.67 s |      174.16 s |     37.05% |
| Worktree startup (ext4)  |     88.65 s |       49.31 s |     44.37% |
| Worktree startup (Btrfs) |     91.35 s |       52.01 s |     43.06% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.36 s |  0.40 s |    -12.01% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.30 s |  0.27 s |     12.09% |                         0 / 0 |
| First failing focused mdtest             | 77.80 s | 57.39 s |     26.24% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.35 s |  1.20 s |     10.91% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.19 s | 24.91 s |     -2.98% |                         3 / 3 |
| Full semantic package tests              | 74.41 s | 47.31 s |     36.43% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.34 s | 14.79 s |     39.23% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.01 s |  2.09 s |     -4.22% |                         0 / 0 |
| Clippy with all targets and features     | 71.08 s | 24.34 s |     65.76% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 274.57–279.04 s for Rust and 172.20–177.05 s for Ohm. Initial CLI build medians are 108.53 s and 92.97 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.20 s |          87.45 s | 88.65 s | 87.64–90.26 s |               304 |                    87.00 s |
| Ohm + shared build                 |   1.30 s |          53.32 s | 54.53 s | 54.19–55.15 s |                80 |                    69.86 s |
| Ohm + shared build + trust opt-ins |   1.29 s |          48.00 s | 49.31 s | 49.14–51.13 s |                36 |                    69.62 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.15 s |          90.18 s | 91.35 s | 88.97–92.17 s |               304 |                    88.71 s |
| Ohm + shared build                 |   1.22 s |          54.85 s | 56.01 s | 55.23–57.20 s |                80 |                    69.33 s |
| Ohm + shared build + trust opt-ins |   2.33 s |          49.50 s | 52.01 s | 51.83–53.42 s |                15 |                    68.27 s |

The trusted Btrfs runs seed 2728 files, including 2690 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Genoa Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
