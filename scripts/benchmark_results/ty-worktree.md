# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-11 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-11 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    345.85 s |      210.15 s |     39.24% |
| Worktree startup (ext4)  |    122.22 s |       67.69 s |     44.62% |
| Worktree startup (Btrfs) |    132.79 s |       13.22 s |     90.04% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.39 s |  0.42 s |     -7.45% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.71 s |  0.38 s |     47.13% |                         0 / 0 |
| First failing focused mdtest             | 97.20 s | 70.19 s |     27.78% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.61 s |  1.61 s |     -0.09% |                         0 / 0 |
| Focused mdtest after Rust fix            | 29.70 s | 28.65 s |      3.50% |                         3 / 3 |
| Full semantic package tests              | 93.04 s | 58.56 s |     37.06% |                         2 / 2 |
| Rebuild CLI with its original features   | 29.00 s | 15.73 s |     45.77% |                         6 / 6 |
| Compare 24 diagnostic results            |  3.07 s |  2.97 s |      3.35% |                         0 / 0 |
| Clippy with all targets and features     | 88.78 s | 30.18 s |     66.01% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 342.19–354.00 s for Rust and 207.73–211.72 s for Ohm. Initial CLI build medians are 130.41 s and 114.09 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   2.14 s |         120.08 s | 122.22 s | 106.59–122.59 s |               304 |                   115.68 s |
| Ohm + shared build                 |   2.07 s |          68.37 s |  70.45 s |   67.26–72.67 s |                80 |                    87.62 s |
| Ohm + shared build + trust opt-ins |   1.46 s |          65.10 s |  67.69 s |   64.21–72.52 s |                36 |                    89.57 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   2.76 s |         130.03 s | 132.79 s | 120.80–135.65 s |               304 |                   125.11 s |
| Ohm + shared build                 |   2.72 s |          69.95 s |  72.67 s |   72.11–78.33 s |                80 |                    91.97 s |
| Ohm + shared build + trust opt-ins |   4.36 s |           8.21 s |  13.22 s |   11.94–13.81 s |                 5 |                    94.60 s |

The trusted Btrfs runs seed 2739 files, including 2701 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Milan Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
