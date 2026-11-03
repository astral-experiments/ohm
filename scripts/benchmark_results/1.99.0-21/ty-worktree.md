# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-21 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-21 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    363.95 s |      224.32 s |     38.36% |
| Worktree startup (ext4)  |    115.18 s |       64.24 s |     44.23% |
| Worktree startup (Btrfs) |    129.26 s |       12.38 s |     90.42% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.53 s |  0.54 s |     -1.61% |                         0 / 0 |
| Verify original diagnostics and save CLI |   0.47 s |  0.37 s |     21.27% |                         0 / 0 |
| First failing focused mdtest             | 102.93 s | 73.11 s |     28.97% |                     116 / 116 |
| Repeat after Markdown-only edit          |   1.81 s |  1.65 s |      9.08% |                         0 / 0 |
| Focused mdtest after Rust fix            |  31.68 s | 32.82 s |     -3.61% |                         3 / 3 |
| Full semantic package tests              |  99.45 s | 59.18 s |     40.49% |                         2 / 2 |
| Rebuild CLI with its original features   |  31.22 s | 19.34 s |     38.06% |                         6 / 6 |
| Compare 24 diagnostic results            |   3.30 s |  3.13 s |      4.92% |                         0 / 0 |
| Clippy with all targets and features     |  97.37 s | 31.58 s |     67.56% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 339.69–374.15 s for Rust and 218.68–231.06 s for Ohm. Initial CLI build medians are 138.26 s and 116.07 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.40 s |         113.72 s | 115.18 s | 107.06–115.55 s |               304 |                   115.26 s |
| Ohm + shared build                 |   1.47 s |          67.13 s |  68.61 s |   67.62–71.32 s |                80 |                    87.00 s |
| Ohm + shared build + trust opt-ins |   1.55 s |          62.69 s |  64.24 s |   63.90–65.96 s |                36 |                    86.32 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.83 s |         127.17 s | 129.26 s | 117.50–133.83 s |               304 |                   120.81 s |
| Ohm + shared build                 |   1.98 s |          72.21 s |  74.25 s |   73.28–74.54 s |                80 |                    91.16 s |
| Ohm + shared build + trust opt-ins |   3.72 s |           8.36 s |  12.38 s |   11.99–13.79 s |                 5 |                    90.96 s |

The trusted Btrfs runs seed 2734 files, including 2696 reflinked files. Each filesystem has its own stock comparison.

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
