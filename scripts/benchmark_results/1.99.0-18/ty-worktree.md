# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-18 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-18 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    380.39 s |      225.01 s |     40.85% |
| Worktree startup (ext4)  |    142.96 s |       68.46 s |     52.11% |
| Worktree startup (Btrfs) |    152.88 s |       13.43 s |     91.22% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.61 s |  0.46 s |     25.76% |                         0 / 0 |
| Verify original diagnostics and save CLI |   0.49 s |  0.36 s |     25.50% |                         0 / 0 |
| First failing focused mdtest             | 106.00 s | 73.76 s |     30.41% |                     116 / 116 |
| Repeat after Markdown-only edit          |   1.88 s |  1.68 s |     10.64% |                         0 / 0 |
| Focused mdtest after Rust fix            |  31.41 s | 31.20 s |      0.64% |                         3 / 3 |
| Full semantic package tests              | 103.60 s | 61.75 s |     40.39% |                         2 / 2 |
| Rebuild CLI with its original features   |  31.18 s | 17.63 s |     43.45% |                         6 / 6 |
| Compare 24 diagnostic results            |   3.69 s |  3.35 s |      9.17% |                         0 / 0 |
| Clippy with all targets and features     | 100.61 s | 32.74 s |     67.46% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 376.71–385.71 s for Rust and 222.85–227.36 s for Ohm. Initial CLI build medians are 142.27 s and 120.65 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.26 s |         141.64 s | 142.96 s | 117.10–145.47 s |               304 |                   134.91 s |
| Ohm + shared build                 |   1.41 s |          73.27 s |  74.72 s |   73.55–74.87 s |                80 |                    95.68 s |
| Ohm + shared build + trust opt-ins |   1.46 s |          67.30 s |  68.46 s |   66.21–71.53 s |                36 |                    94.67 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.78 s |         150.77 s | 152.88 s | 133.28–157.32 s |               304 |                   142.23 s |
| Ohm + shared build                 |   1.95 s |          79.66 s |  81.61 s |   79.03–87.82 s |                80 |                    95.36 s |
| Ohm + shared build + trust opt-ins |   3.74 s |           9.69 s |  13.43 s |   12.55–17.97 s |                 5 |                   102.05 s |

The trusted Btrfs runs seed 2733 files, including 2695 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Milan Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
