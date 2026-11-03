# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-20 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-20 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    357.25 s |      214.58 s |     39.94% |
| Worktree startup (ext4)  |    122.75 s |       65.94 s |     46.28% |
| Worktree startup (Btrfs) |    114.85 s |       11.27 s |     90.19% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.57 s |  0.55 s |      4.70% |                         0 / 0 |
| Verify original diagnostics and save CLI |   0.40 s |  0.39 s |      3.30% |                         0 / 0 |
| First failing focused mdtest             | 101.87 s | 71.53 s |     29.79% |                     116 / 116 |
| Repeat after Markdown-only edit          |   1.75 s |  1.74 s |      0.97% |                         0 / 0 |
| Focused mdtest after Rust fix            |  30.91 s | 25.51 s |     17.47% |                         3 / 3 |
| Full semantic package tests              |  96.72 s | 59.78 s |     38.19% |                         2 / 2 |
| Rebuild CLI with its original features   |  29.65 s | 18.75 s |     36.77% |                         6 / 6 |
| Compare 24 diagnostic results            |   3.07 s |  3.05 s |      0.58% |                         0 / 0 |
| Clippy with all targets and features     |  93.34 s | 31.06 s |     66.73% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 345.40–362.68 s for Rust and 213.13–217.11 s for Ohm. Initial CLI build medians are 138.08 s and 117.03 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.54 s |         121.12 s | 122.75 s | 108.27–122.91 s |               304 |                   122.20 s |
| Ohm + shared build                 |   1.75 s |          68.71 s |  70.54 s |   68.89–74.01 s |                80 |                    85.77 s |
| Ohm + shared build + trust opt-ins |   1.83 s |          64.11 s |  65.94 s |   64.84–67.59 s |                36 |                    88.89 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.86 s |         112.99 s | 114.85 s | 114.40–122.84 s |               304 |                   112.57 s |
| Ohm + shared build                 |   1.86 s |          69.16 s |  71.13 s |   70.01–71.76 s |                80 |                    88.44 s |
| Ohm + shared build + trust opt-ins |   3.33 s |           7.95 s |  11.27 s |   10.83–12.32 s |                 5 |                    86.67 s |

The trusted Btrfs runs seed 2741 files, including 2703 reflinked files. Each filesystem has its own stock comparison.

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
