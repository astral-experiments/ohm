# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-24 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-24 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    275.99 s |      168.35 s |     39.00% |
| Worktree startup (ext4)  |     88.80 s |       49.46 s |     44.30% |
| Worktree startup (Btrfs) |     88.59 s |        8.89 s |     89.96% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.29 s |  0.31 s |     -7.59% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.30 s |  0.26 s |     11.44% |                         0 / 0 |
| First failing focused mdtest             | 78.12 s | 55.36 s |     29.14% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.39 s |  1.14 s |     18.39% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.16 s | 13.95 s |     42.26% |                         3 / 3 |
| Full semantic package tests              | 73.13 s | 45.59 s |     37.66% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.22 s | 24.15 s |      0.31% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.23 s |  2.18 s |      2.49% |                         0 / 0 |
| Clippy with all targets and features     | 70.10 s | 23.75 s |     66.11% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 271.90–282.58 s for Rust and 167.01–170.83 s for Ohm. Initial CLI build medians are 107.90 s and 89.23 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   0.95 s |          87.90 s | 88.80 s | 87.10–95.48 s |               304 |                    85.15 s |
| Ohm + shared build                 |   1.03 s |          51.65 s | 52.68 s | 52.57–53.53 s |                80 |                    66.88 s |
| Ohm + shared build + trust opt-ins |   1.11 s |          48.35 s | 49.46 s | 49.09–50.66 s |                36 |                    67.19 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.09 s |          87.50 s | 88.59 s | 87.34–88.88 s |               304 |                    87.09 s |
| Ohm + shared build                 |   1.22 s |          53.21 s | 54.42 s | 54.28–54.59 s |                80 |                    68.34 s |
| Ohm + shared build + trust opt-ins |   2.02 s |           6.73 s |  8.89 s |   8.33–9.18 s |                 5 |                    66.92 s |

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
