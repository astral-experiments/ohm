# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-15 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-15 | Time saved |
| ------------------------ | ----------: | ------------: | ---------: |
| ty session               |    607.89 s |      320.34 s |     47.30% |
| Worktree startup (ext4)  |    161.21 s |       78.11 s |     51.55% |
| Worktree startup (Btrfs) |    175.11 s |       14.15 s |     91.92% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |     Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | -------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |   0.96 s |  0.88 s |      8.06% |                         0 / 0 |
| Verify original diagnostics and save CLI |   0.93 s |  0.63 s |     32.90% |                         0 / 0 |
| First failing focused mdtest             | 166.97 s | 92.49 s |     44.60% |                     116 / 116 |
| Repeat after Markdown-only edit          |   2.36 s |  2.42 s |     -2.47% |                         0 / 0 |
| Focused mdtest after Rust fix            |  49.21 s | 47.26 s |      3.96% |                         3 / 3 |
| Full semantic package tests              | 152.11 s | 80.07 s |     47.36% |                         2 / 2 |
| Rebuild CLI with its original features   |  44.77 s | 44.59 s |      0.41% |                         6 / 6 |
| Compare 24 diagnostic results            |   4.97 s |  5.08 s |     -2.20% |                         0 / 0 |
| Clippy with all targets and features     | 190.57 s | 43.42 s |     77.22% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 534.12–660.37 s for Rust and 308.63–332.38 s for Ohm. Initial CLI build medians are 190.12 s and 140.38 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.97 s |         159.24 s | 161.21 s | 155.50–166.90 s |               304 |                   154.29 s |
| Ohm + shared build                 |   2.58 s |          83.82 s |  86.40 s |   84.30–86.96 s |                80 |                   102.46 s |
| Ohm + shared build + trust opt-ins |   2.31 s |          75.79 s |  78.11 s |   77.52–82.29 s |                36 |                   102.42 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.86 s |         173.25 s | 175.11 s | 150.66–188.41 s |               304 |                   157.41 s |
| Ohm + shared build                 |   2.26 s |          88.96 s |  91.22 s |   85.08–91.77 s |                80 |                   108.95 s |
| Ohm + shared build + trust opt-ins |   3.44 s |          10.91 s |  14.15 s |   13.56–17.47 s |                 5 |                   107.13 s |

The trusted Btrfs runs seed 2737 files, including 2699 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Milan Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
