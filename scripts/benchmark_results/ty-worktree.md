# ty session and worktree startup

We measured stock Rust 1.99.0 and the Ohm 1.99.0-28 qualification SDK on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-28 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    278.48 s |      186.49 s |     33.03% |
| Worktree startup (ext4)  |     87.75 s |       51.61 s |     41.19% |
| Worktree startup (Btrfs) |     88.71 s |       50.19 s |     43.42% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.55 s |  0.43 s |     20.62% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.49 s |  0.43 s |     13.90% |                         0 / 0 |
| First failing focused mdtest             | 78.40 s | 56.87 s |     27.47% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.32 s |  1.26 s |      4.75% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.08 s | 24.61 s |     -2.21% |                         3 / 3 |
| Full semantic package tests              | 74.73 s | 47.96 s |     35.83% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.66 s | 25.11 s |     -1.83% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.12 s |  2.38 s |    -12.30% |                         0 / 0 |
| Clippy with all targets and features     | 70.69 s | 25.03 s |     64.60% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 274.86–285.25 s for Rust and 184.38–189.53 s for Ohm. Initial CLI build medians are 110.41 s and 94.76 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.05 s |          86.71 s | 87.75 s | 86.50–88.49 s |               304 |                    86.04 s |
| Ohm + shared build                 |   1.13 s |          53.45 s | 54.58 s | 54.09–55.87 s |                80 |                    68.68 s |
| Ohm + shared build + trust opt-ins |   1.11 s |          50.34 s | 51.61 s | 49.25–55.29 s |                36 |                    68.32 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.06 s |          87.65 s | 88.71 s | 88.39–89.60 s |               304 |                    87.83 s |
| Ohm + shared build                 |   1.12 s |          53.62 s | 54.75 s | 54.51–55.18 s |                80 |                    68.75 s |
| Ohm + shared build + trust opt-ins |   2.61 s |          47.50 s | 50.19 s | 50.11–50.24 s |                15 |                    68.85 s |

The trusted Btrfs runs seed 2726 files, including 2688 reflinked files. Each filesystem has its own stock comparison.

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
