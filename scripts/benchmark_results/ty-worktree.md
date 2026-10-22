# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-7 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-7 | Time saved |
| ------------------------ | ----------: | -----------: | ---------: |
| ty session               |    282.53 s |     178.24 s |     36.91% |
| Worktree startup (ext4)  |     88.42 s |      51.71 s |     41.52% |
| Worktree startup (Btrfs) |     89.13 s |       9.49 s |     89.36% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.41 s |  0.48 s |    -16.35% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.39 s |  0.39 s |     -0.05% |                         0 / 0 |
| First failing focused mdtest             | 78.07 s | 59.83 s |     23.37% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.34 s |  1.31 s |      2.10% |                         0 / 0 |
| Focused mdtest after Rust fix            | 24.51 s | 14.87 s |     39.32% |                         3 / 3 |
| Full semantic package tests              | 75.53 s | 47.70 s |     36.84% |                         2 / 2 |
| Rebuild CLI with its original features   | 25.08 s | 23.20 s |      7.50% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.41 s |  2.36 s |      2.32% |                         0 / 0 |
| Clippy with all targets and features     | 72.96 s | 25.54 s |     64.99% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 275.71–288.03 s for Rust and 172.84–183.42 s for Ohm. Initial CLI build medians are 109.41 s and 94.89 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.58 s |          86.84 s | 88.42 s | 87.48–89.77 s |               304 |                    88.02 s |
| Ohm + shared build                 |   1.81 s |          54.31 s | 56.38 s | 55.68–57.63 s |                80 |                    70.26 s |
| Ohm + shared build + trust opt-ins |   1.70 s |          49.89 s | 51.71 s | 51.47–51.95 s |                36 |                    69.84 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.56 s |          87.56 s | 89.13 s | 88.71–89.99 s |               304 |                    88.54 s |
| Ohm + shared build                 |   1.76 s |          54.11 s | 56.11 s | 55.54–56.42 s |                80 |                    71.50 s |
| Ohm + shared build + trust opt-ins |   3.23 s |           6.24 s |  9.49 s |  9.47–10.22 s |                 5 |                    71.17 s |

The trusted Btrfs runs seed 2733 files, including 2695 reflinked files. Each filesystem has its own stock comparison.

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

The [evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-7-e2a2b69a25e7) contains command logs, CPU traces, source and test checks, and excluded attempts. Its SHA-256 is `e2a2b69a25e740b5a7728a410f5c1e21dacbfc5b5808d63b00d64eb459bd73e1`.
