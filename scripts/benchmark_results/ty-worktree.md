# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-32 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-32 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    307.71 s |      192.40 s |     37.47% |
| Worktree startup (ext4)  |     99.47 s |       53.13 s |     46.59% |
| Worktree startup (Btrfs) |     98.11 s |       58.82 s |     40.04% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.51 s |  0.63 s |    -22.06% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.42 s |  0.34 s |     19.64% |                         0 / 0 |
| First failing focused mdtest             | 86.37 s | 59.19 s |     31.47% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.41 s |  1.39 s |      1.63% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.93 s | 26.22 s |     -5.18% |                         3 / 3 |
| Full semantic package tests              | 80.99 s | 46.79 s |     42.22% |                         2 / 2 |
| Rebuild CLI with its original features   | 26.51 s | 26.38 s |      0.49% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.41 s |  2.29 s |      4.94% |                         0 / 0 |
| Clippy with all targets and features     | 81.22 s | 25.45 s |     68.66% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 298.20–317.37 s for Rust and 185.25–199.34 s for Ohm. Initial CLI build medians are 116.03 s and 93.59 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.26 s |          98.32 s | 99.47 s | 90.83–99.82 s |               304 |                    95.25 s |
| Ohm + shared build                 |   1.27 s |          55.89 s | 57.16 s | 56.22–58.23 s |                80 |                    71.50 s |
| Ohm + shared build + trust opt-ins |   1.29 s |          51.67 s | 53.13 s | 50.32–55.59 s |                36 |                    72.23 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |    Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | -------------: | ----------------: | -------------------------: |
| Rust                               |   1.33 s |          96.78 s | 98.11 s | 96.99–114.22 s |               304 |                   108.74 s |
| Ohm + shared build                 |   1.47 s |          64.68 s | 66.29 s |  55.65–68.09 s |                80 |                    75.66 s |
| Ohm + shared build + trust opt-ins |   3.73 s |          55.09 s | 58.82 s |  55.13–59.36 s |                15 |                    78.40 s |

The trusted Btrfs runs seed 2739 files, including 2701 reflinked files. Each filesystem has its own stock comparison.

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
