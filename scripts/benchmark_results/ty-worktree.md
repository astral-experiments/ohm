# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-29 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-29 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    290.40 s |      187.93 s |     35.28% |
| Worktree startup (ext4)  |     93.03 s |       50.89 s |     45.29% |
| Worktree startup (Btrfs) |     94.22 s |       53.82 s |     42.87% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.38 s |  0.39 s |     -2.03% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.57 s |  0.29 s |     48.92% |                         0 / 0 |
| First failing focused mdtest             | 83.51 s | 56.31 s |     32.57% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.43 s |  1.45 s |     -1.40% |                         0 / 0 |
| Focused mdtest after Rust fix            | 25.66 s | 26.36 s |     -2.70% |                         3 / 3 |
| Full semantic package tests              | 76.68 s | 47.33 s |     38.27% |                         2 / 2 |
| Rebuild CLI with its original features   | 25.25 s | 26.46 s |     -4.80% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.50 s |  2.57 s |     -2.56% |                         0 / 0 |
| Clippy with all targets and features     | 72.64 s | 25.24 s |     65.26% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 287.03–294.20 s for Rust and 185.18–190.02 s for Ohm. Initial CLI build medians are 112.38 s and 92.16 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.03 s |          91.83 s | 93.03 s | 91.13–93.28 s |               304 |                    91.65 s |
| Ohm + shared build                 |   1.20 s |          53.27 s | 54.47 s | 53.80–57.22 s |                80 |                    69.67 s |
| Ohm + shared build + trust opt-ins |   1.14 s |          49.61 s | 50.89 s | 49.82–50.97 s |                36 |                    69.16 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.12 s |          93.09 s | 94.22 s | 90.62–94.98 s |               304 |                    90.43 s |
| Ohm + shared build                 |   1.29 s |          55.08 s | 56.67 s | 55.83–59.49 s |                80 |                    70.26 s |
| Ohm + shared build + trust opt-ins |   3.98 s |          49.74 s | 53.82 s | 53.72–55.00 s |                15 |                    69.42 s |

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
