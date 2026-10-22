# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-8 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-8 | Time saved |
| ------------------------ | ----------: | -----------: | ---------: |
| ty session               |    279.04 s |     175.82 s |     36.99% |
| Worktree startup (ext4)  |     89.47 s |      53.13 s |     40.61% |
| Worktree startup (Btrfs) |     89.86 s |       9.43 s |     89.51% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.41 s |  0.44 s |     -6.86% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.39 s |  0.39 s |     -0.10% |                         0 / 0 |
| First failing focused mdtest             | 78.06 s | 58.56 s |     24.98% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.32 s |  1.28 s |      2.99% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.28 s | 23.49 s |      3.25% |                         3 / 3 |
| Full semantic package tests              | 74.15 s | 47.29 s |     36.22% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.26 s | 14.55 s |     40.00% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.34 s |  2.35 s |     -0.38% |                         0 / 0 |
| Clippy with all targets and features     | 71.45 s | 25.84 s |     63.84% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 275.19–287.34 s for Rust and 174.40–177.62 s for Ohm. Initial CLI build medians are 108.18 s and 92.84 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   2.00 s |          87.78 s | 89.47 s | 89.37–91.86 s |               304 |                    87.87 s |
| Ohm + shared build                 |   1.96 s |          54.99 s | 56.95 s | 56.45–57.78 s |                80 |                    70.68 s |
| Ohm + shared build + trust opt-ins |   1.79 s |          51.17 s | 53.13 s | 51.90–56.40 s |                36 |                    71.63 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.57 s |          88.29 s | 89.86 s | 89.69–90.88 s |               304 |                    88.48 s |
| Ohm + shared build                 |   1.72 s |          55.18 s | 56.93 s | 56.78–57.02 s |                80 |                    71.21 s |
| Ohm + shared build + trust opt-ins |   3.18 s |           6.26 s |  9.43 s |   9.25–9.62 s |                 5 |                    71.01 s |

The trusted Btrfs runs seed 2723 files, including 2685 reflinked files. Each filesystem has its own stock comparison.

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

The [evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-8-3dd5a5d42175) contains command logs, CPU traces, source and test checks, and excluded attempts. Its SHA-256 is `3dd5a5d42175e66273b7f81d4ffb3049e933b275531b48a4b0ab8c78d39efeb6`.
