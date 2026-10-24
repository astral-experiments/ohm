# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-10 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-10 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    408.82 s |      259.85 s |     36.44% |
| Worktree startup (ext4)  |    149.78 s |       76.31 s |     49.05% |
| Worktree startup (Btrfs) |    142.89 s |       12.83 s |     91.02% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.71 s |  0.67 s |      6.13% |                         0 / 0 |
| Verify original diagnostics and save CLI |   0.56 s |  0.49 s |     12.52% |                         0 / 0 |
| First failing focused mdtest             | 114.56 s | 81.33 s |     29.01% |                     116 / 116 |
| Repeat after Markdown-only edit          |   2.01 s |  2.03 s |     -1.25% |                         0 / 0 |
| Focused mdtest after Rust fix            |  34.68 s | 34.03 s |      1.86% |                         3 / 3 |
| Full semantic package tests              | 107.85 s | 65.51 s |     39.26% |                         2 / 2 |
| Rebuild CLI with its original features   |  33.78 s | 35.32 s |     -4.55% |                         6 / 6 |
| Compare 24 diagnostic results            |   3.37 s |  3.29 s |      2.28% |                         0 / 0 |
| Clippy with all targets and features     | 106.32 s | 34.62 s |     67.44% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 399.42–426.20 s for Rust and 254.71–267.46 s for Ohm. Initial CLI build medians are 151.33 s and 129.41 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.92 s |         147.86 s | 149.78 s | 122.57–151.67 s |               304 |                   139.08 s |
| Ohm + shared build                 |   2.19 s |          81.55 s |  83.74 s |   80.41–93.05 s |                80 |                   101.86 s |
| Ohm + shared build + trust opt-ins |   2.02 s |          74.38 s |  76.31 s |   73.04–78.31 s |                36 |                   102.35 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.89 s |         141.01 s | 142.89 s | 133.10–151.91 s |               304 |                   143.07 s |
| Ohm + shared build                 |   1.87 s |          85.02 s |  86.89 s |   84.84–88.84 s |                80 |                   106.92 s |
| Ohm + shared build + trust opt-ins |   3.27 s |           9.56 s |  12.83 s |   12.36–16.91 s |                 5 |                   106.26 s |

The trusted Btrfs runs seed 2727 files, including 2689 reflinked files. Each filesystem has its own stock comparison.

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
