# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-23 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-23 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    273.17 s |      180.50 s |     33.92% |
| Worktree startup (ext4)  |     89.22 s |       51.15 s |     42.67% |
| Worktree startup (Btrfs) |     88.61 s |        8.91 s |     89.95% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.36 s |  0.39 s |     -6.48% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.29 s |  0.27 s |      9.55% |                         0 / 0 |
| First failing focused mdtest             | 78.26 s | 57.02 s |     27.15% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.37 s |  1.26 s |      7.78% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.42 s | 20.14 s |     17.51% |                         3 / 3 |
| Full semantic package tests              | 72.77 s | 48.16 s |     33.82% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.02 s | 24.21 s |     -0.78% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.14 s |  2.11 s |      1.28% |                         0 / 0 |
| Clippy with all targets and features     | 68.69 s | 24.94 s |     63.70% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 271.64–276.13 s for Rust and 178.53–184.52 s for Ohm. Initial CLI build medians are 107.97 s and 93.42 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.16 s |          88.07 s | 89.22 s | 87.98–90.27 s |               304 |                    88.16 s |
| Ohm + shared build                 |   1.17 s |          55.01 s | 56.15 s | 55.24–57.61 s |                80 |                    71.07 s |
| Ohm + shared build + trust opt-ins |   1.09 s |          49.98 s | 51.15 s | 49.97–52.26 s |                36 |                    70.21 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.15 s |          87.46 s | 88.61 s | 88.25–90.05 s |               304 |                    87.51 s |
| Ohm + shared build                 |   1.41 s |          54.96 s | 56.37 s | 55.31–60.43 s |                80 |                    68.91 s |
| Ohm + shared build + trust opt-ins |   2.34 s |           6.54 s |  8.91 s |   8.44–9.32 s |                 5 |                    68.90 s |

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
