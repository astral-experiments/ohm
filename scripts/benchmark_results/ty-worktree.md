# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-14 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-14 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    348.66 s |      195.53 s |     43.92% |
| Worktree startup (ext4)  |    117.00 s |       62.64 s |     46.46% |
| Worktree startup (Btrfs) |    117.67 s |       11.66 s |     90.09% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.49 s |  0.56 s |    -16.04% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.47 s |  0.39 s |     18.23% |                         0 / 0 |
| First failing focused mdtest             | 99.10 s | 68.58 s |     30.80% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.76 s |  1.64 s |      7.21% |                         0 / 0 |
| Focused mdtest after Rust fix            | 30.23 s | 16.19 s |     46.45% |                         3 / 3 |
| Full semantic package tests              | 93.58 s | 58.38 s |     37.62% |                         2 / 2 |
| Rebuild CLI with its original features   | 29.47 s | 14.77 s |     49.89% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.87 s |  2.91 s |     -1.48% |                         0 / 0 |
| Clippy with all targets and features     | 90.45 s | 30.45 s |     66.34% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 343.00–352.61 s for Rust and 193.92–196.39 s for Ohm. Initial CLI build medians are 133.18 s and 112.88 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.44 s |         115.53 s | 117.00 s | 108.79–124.03 s |               304 |                   114.86 s |
| Ohm + shared build                 |   1.62 s |          64.90 s |  66.31 s |   65.99–70.70 s |                80 |                    84.32 s |
| Ohm + shared build + trust opt-ins |   1.70 s |          61.10 s |  62.64 s |   60.93–64.13 s |                36 |                    85.67 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.66 s |         116.01 s | 117.67 s | 114.81–124.01 s |               304 |                   119.42 s |
| Ohm + shared build                 |   1.67 s |          68.18 s |  69.93 s |   68.70–70.12 s |                80 |                    87.08 s |
| Ohm + shared build + trust opt-ins |   3.39 s |           8.55 s |  11.66 s |   11.28–13.58 s |                 5 |                    87.72 s |

The trusted Btrfs runs seed 2730 files, including 2692 reflinked files. Each filesystem has its own stock comparison.

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
