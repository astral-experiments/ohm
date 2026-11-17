# ty session and worktree startup

We measured stock Rust 1.99.0 and published Ohm 1.99.0-34 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-34 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    303.96 s |      178.63 s |     41.23% |
| Worktree startup (ext4)  |     95.77 s |       57.40 s |     40.07% |
| Worktree startup (Btrfs) |    103.54 s |       59.19 s |     42.83% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.38 s |  0.63 s |    -64.02% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.37 s |  0.31 s |     17.96% |                         0 / 0 |
| First failing focused mdtest             | 82.17 s | 66.32 s |     19.29% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.43 s |  1.35 s |      5.68% |                         0 / 0 |
| Focused mdtest after Rust fix            | 25.91 s | 16.28 s |     37.17% |                         3 / 3 |
| Full semantic package tests              | 81.80 s | 48.09 s |     41.21% |                         2 / 2 |
| Rebuild CLI with its original features   | 27.17 s | 16.94 s |     37.66% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.41 s |  2.35 s |      2.52% |                         0 / 0 |
| Clippy with all targets and features     | 77.54 s | 25.31 s |     67.36% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 286.92–325.55 s for Rust and 166.63–190.30 s for Ohm. Initial CLI build medians are 114.61 s and 99.78 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.10 s |          94.67 s | 95.77 s | 94.49–97.36 s |               304 |                    96.50 s |
| Ohm + shared build                 |   1.17 s |          59.66 s | 60.77 s | 58.71–62.61 s |                80 |                    73.59 s |
| Ohm + shared build + trust opt-ins |   1.16 s |          56.29 s | 57.40 s | 57.22–58.34 s |                36 |                    76.73 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |    Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | -------------: | ----------------: | -------------------------: |
| Rust                               |   1.16 s |         102.39 s | 103.54 s | 99.43–105.11 s |               304 |                    99.18 s |
| Ohm + shared build                 |   1.33 s |          60.27 s |  61.59 s |  60.50–61.60 s |                80 |                    77.41 s |
| Ohm + shared build + trust opt-ins |   4.43 s |          54.71 s |  59.19 s |  59.06–62.15 s |                15 |                    76.53 s |

The trusted Btrfs runs seed 4425 files, including 4387 reflinked files. Each filesystem has its own stock comparison.

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
