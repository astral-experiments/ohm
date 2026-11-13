# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-33 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-33 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    323.79 s |      181.28 s |     44.01% |
| Worktree startup (ext4)  |    100.27 s |       59.05 s |     41.11% |
| Worktree startup (Btrfs) |    116.61 s |       67.84 s |     41.82% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.40 s |  0.46 s |    -14.40% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.78 s |  0.40 s |     49.10% |                         0 / 0 |
| First failing focused mdtest             | 86.63 s | 64.40 s |     25.66% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.38 s |  1.35 s |      2.50% |                         0 / 0 |
| Focused mdtest after Rust fix            | 28.70 s | 17.42 s |     39.30% |                         3 / 3 |
| Full semantic package tests              | 86.91 s | 48.30 s |     44.42% |                         2 / 2 |
| Rebuild CLI with its original features   | 29.01 s | 18.18 s |     37.32% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.54 s |  2.41 s |      5.10% |                         0 / 0 |
| Clippy with all targets and features     | 86.49 s | 27.52 s |     68.19% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 316.02–331.89 s for Rust and 175.08–188.01 s for Ohm. Initial CLI build medians are 116.94 s and 99.21 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |    Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | -------------: | ----------------: | -------------------------: |
| Rust                               |   1.10 s |          99.17 s | 100.27 s | 88.42–106.84 s |               304 |                    98.99 s |
| Ohm + shared build                 |   1.51 s |          55.99 s |  57.31 s |  56.29–62.68 s |                80 |                    71.70 s |
| Ohm + shared build + trust opt-ins |   1.44 s |          57.60 s |  59.05 s |  58.11–60.67 s |                36 |                    77.26 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |    Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | -------------: | ----------------: | -------------------------: |
| Rust                               |   1.25 s |         115.12 s | 116.61 s | 91.93–119.37 s |               304 |                   106.24 s |
| Ohm + shared build                 |   1.63 s |          66.40 s |  68.41 s |  67.51–68.80 s |                80 |                    83.45 s |
| Ohm + shared build + trust opt-ins |   4.95 s |          62.90 s |  67.84 s |  60.83–68.17 s |                15 |                    81.62 s |

The trusted Btrfs runs seed 4068 files, including 4030 reflinked files. Each filesystem has its own stock comparison.

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
