# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-31 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-31 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    305.32 s |      188.06 s |     38.41% |
| Worktree startup (ext4)  |     94.32 s |       52.78 s |     44.04% |
| Worktree startup (Btrfs) |    112.61 s |       53.66 s |     52.35% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.53 s |  0.50 s |      5.50% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.47 s |  0.30 s |     35.45% |                         0 / 0 |
| First failing focused mdtest             | 86.87 s | 56.11 s |     35.41% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.58 s |  1.19 s |     24.15% |                         0 / 0 |
| Focused mdtest after Rust fix            | 27.88 s | 26.33 s |      5.56% |                         3 / 3 |
| Full semantic package tests              | 79.88 s | 47.52 s |     40.51% |                         2 / 2 |
| Rebuild CLI with its original features   | 26.69 s | 26.61 s |      0.32% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.32 s |  2.20 s |      5.10% |                         0 / 0 |
| Clippy with all targets and features     | 78.99 s | 25.23 s |     68.06% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 295.80–314.24 s for Rust and 187.64–188.72 s for Ohm. Initial CLI build medians are 116.06 s and 90.05 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.14 s |          93.24 s | 94.32 s | 90.83–94.92 s |               304 |                    90.26 s |
| Ohm + shared build                 |   1.14 s |          53.42 s | 54.56 s | 54.36–57.15 s |                80 |                    69.07 s |
| Ohm + shared build + trust opt-ins |   1.26 s |          51.52 s | 52.78 s | 49.14–54.14 s |                36 |                    68.28 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.22 s |         111.39 s | 112.61 s | 102.47–112.78 s |               304 |                    98.96 s |
| Ohm + shared build                 |   1.32 s |          59.86 s |  61.24 s |   58.90–61.41 s |                80 |                    73.85 s |
| Ohm + shared build + trust opt-ins |   4.70 s |          50.47 s |  53.66 s |   53.24–58.89 s |                15 |                    72.37 s |

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
