# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-22 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-22 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    352.43 s |      204.92 s |     41.85% |
| Worktree startup (ext4)  |    116.30 s |       65.34 s |     43.82% |
| Worktree startup (Btrfs) |    118.42 s |       11.90 s |     89.95% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.68 s |  0.96 s |    -40.75% |                         0 / 1 |
| Verify original diagnostics and save CLI |   0.40 s |  0.42 s |     -5.92% |                         0 / 0 |
| First failing focused mdtest             | 100.04 s | 71.04 s |     28.99% |                     116 / 116 |
| Repeat after Markdown-only edit          |   1.76 s |  1.87 s |     -6.23% |                         0 / 1 |
| Focused mdtest after Rust fix            |  30.29 s | 17.44 s |     42.43% |                         3 / 3 |
| Full semantic package tests              |  95.54 s | 59.44 s |     37.79% |                         2 / 3 |
| Rebuild CLI with its original features   |  28.95 s | 18.07 s |     37.60% |                         6 / 6 |
| Compare 24 diagnostic results            |   2.97 s |  2.81 s |      5.43% |                         0 / 0 |
| Clippy with all targets and features     |  91.38 s | 31.07 s |     66.00% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 347.46–355.39 s for Rust and 203.09–206.73 s for Ohm. Initial CLI build medians are 135.05 s and 115.60 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.43 s |         114.88 s | 116.30 s | 108.30–126.29 s |               304 |                   117.66 s |
| Ohm + shared build                 |   1.58 s |          67.71 s |  69.21 s |   68.33–71.08 s |                80 |                    87.13 s |
| Ohm + shared build + trust opt-ins |   1.72 s |          63.55 s |  65.34 s |   64.03–65.70 s |                36 |                    86.57 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.82 s |         116.61 s | 118.42 s | 116.06–121.04 s |               304 |                   120.36 s |
| Ohm + shared build                 |   1.98 s |          70.23 s |  72.21 s |   71.97–72.32 s |                80 |                    90.38 s |
| Ohm + shared build + trust opt-ins |   3.56 s |           8.34 s |  11.90 s |   11.49–12.42 s |                 5 |                    87.97 s |

The trusted Btrfs runs seed 2730 files, including 2692 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Genoa Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
