# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-27 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-27 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    283.31 s |      164.41 s |     41.97% |
| Worktree startup (ext4)  |     92.94 s |       53.59 s |     42.33% |
| Worktree startup (Btrfs) |     98.19 s |       51.38 s |     47.67% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.34 s |  0.39 s |    -13.09% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.30 s |  0.27 s |     11.65% |                         0 / 0 |
| First failing focused mdtest             | 80.97 s | 57.59 s |     28.88% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.36 s |  1.28 s |      5.93% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.30 s | 13.92 s |     42.73% |                         3 / 3 |
| Full semantic package tests              | 74.99 s | 48.08 s |     35.88% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.68 s | 14.75 s |     40.22% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.06 s |  2.06 s |      0.18% |                         0 / 0 |
| Clippy with all targets and features     | 71.61 s | 24.81 s |     65.35% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 280.90–285.47 s for Rust and 163.63–166.33 s for Ohm. Initial CLI build medians are 110.98 s and 93.88 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.06 s |          91.88 s | 92.94 s | 86.53–93.36 s |               304 |                    91.57 s |
| Ohm + shared build                 |   1.16 s |          57.33 s | 58.49 s | 57.48–59.24 s |                80 |                    72.33 s |
| Ohm + shared build + trust opt-ins |   1.15 s |          52.53 s | 53.59 s | 53.23–54.76 s |                36 |                    69.44 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.08 s |          97.13 s | 98.19 s | 89.90–98.34 s |               304 |                    92.56 s |
| Ohm + shared build                 |   1.27 s |          57.63 s | 58.90 s | 58.25–61.64 s |                80 |                    72.28 s |
| Ohm + shared build + trust opt-ins |   2.80 s |          49.17 s | 51.38 s | 51.36–57.64 s |                15 |                    73.99 s |

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

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
