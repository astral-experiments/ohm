# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-17 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-17 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    340.75 s |      191.72 s |     43.73% |
| Worktree startup (ext4)  |    118.82 s |       61.65 s |     48.11% |
| Worktree startup (Btrfs) |    129.01 s |       11.93 s |     90.75% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.46 s |  0.41 s |     11.20% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.51 s |  0.35 s |     31.14% |                         0 / 0 |
| First failing focused mdtest             | 96.64 s | 68.13 s |     29.50% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.77 s |  1.56 s |     12.08% |                         0 / 0 |
| Focused mdtest after Rust fix            | 29.35 s | 15.31 s |     47.84% |                         3 / 3 |
| Full semantic package tests              | 91.44 s | 56.82 s |     37.86% |                         2 / 2 |
| Rebuild CLI with its original features   | 28.74 s | 15.10 s |     47.46% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.89 s |  3.07 s |     -6.31% |                         0 / 0 |
| Clippy with all targets and features     | 87.65 s | 29.49 s |     66.36% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 337.48–344.98 s for Rust and 190.45–193.39 s for Ohm. Initial CLI build medians are 129.92 s and 110.90 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.24 s |         117.58 s | 118.82 s | 107.61–120.45 s |               304 |                   113.97 s |
| Ohm + shared build                 |   1.16 s |          64.27 s |  65.43 s |   64.51–68.35 s |                80 |                    84.56 s |
| Ohm + shared build + trust opt-ins |   1.26 s |          60.44 s |  61.65 s |   61.35–63.40 s |                36 |                    84.85 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.37 s |         127.67 s | 129.01 s | 117.68–135.56 s |               304 |                   123.38 s |
| Ohm + shared build                 |   1.42 s |          68.17 s |  69.59 s |   68.63–77.83 s |                80 |                    88.83 s |
| Ohm + shared build + trust opt-ins |   2.79 s |           8.13 s |  11.93 s |   10.22–12.08 s |                 5 |                    88.37 s |

The trusted Btrfs runs seed 2736 files, including 2698 reflinked files. Each filesystem has its own stock comparison.

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
