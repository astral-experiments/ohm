# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-30 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-30 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    276.09 s |      181.81 s |     34.15% |
| Worktree startup (ext4)  |     87.69 s |       48.41 s |     44.80% |
| Worktree startup (Btrfs) |     88.23 s |       48.47 s |     45.06% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.54 s |  0.44 s |     18.47% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.46 s |  0.42 s |      9.23% |                         0 / 0 |
| First failing focused mdtest             | 78.58 s | 55.16 s |     29.81% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.43 s |  1.22 s |     14.79% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.42 s | 24.46 s |     -0.15% |                         3 / 3 |
| Full semantic package tests              | 72.70 s | 45.33 s |     37.66% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.33 s | 25.30 s |     -4.02% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.17 s |  2.19 s |     -0.92% |                         0 / 0 |
| Clippy with all targets and features     | 70.13 s | 24.69 s |     64.80% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 271.86–280.66 s for Rust and 178.40–188.57 s for Ohm. Initial CLI build medians are 108.92 s and 89.25 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.05 s |          85.82 s | 87.69 s | 86.87–87.96 s |               304 |                    86.11 s |
| Ohm + shared build                 |   1.17 s |          51.34 s | 52.43 s | 51.41–52.87 s |                80 |                    65.70 s |
| Ohm + shared build + trust opt-ins |   1.30 s |          47.10 s | 48.41 s | 47.73–48.80 s |                36 |                    66.04 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.07 s |          87.16 s | 88.23 s | 87.88–88.98 s |               304 |                    86.12 s |
| Ohm + shared build                 |   1.18 s |          50.95 s | 52.12 s | 51.94–53.12 s |                80 |                    65.40 s |
| Ohm + shared build + trust opt-ins |   2.57 s |          45.77 s | 48.47 s | 47.90–48.56 s |                15 |                    66.33 s |

The trusted Btrfs runs seed 2737 files, including 2699 reflinked files. Each filesystem has its own stock comparison.

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
