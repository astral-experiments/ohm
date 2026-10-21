# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-6 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-6 | Time saved |
| ------------------------ | ----------: | -----------: | ---------: |
| ty session               |    279.48 s |     181.93 s |     34.90% |
| Worktree startup (ext4)  |     90.09 s |      52.46 s |     41.76% |
| Worktree startup (Btrfs) |     92.20 s |       9.52 s |     89.67% |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

These tables leave test/build overlap disabled. The [separate option comparison](ready-tests.md) includes four additional ty replays with the same binaries and the option enabled. This session uses Nextest, whose build-only Cargo invocation disables early test execution.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.41 s |  0.49 s |    -18.14% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.39 s |  0.39 s |     -0.24% |                         0 / 0 |
| First failing focused mdtest             | 78.32 s | 59.46 s |     24.08% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.47 s |  1.55 s |     -4.80% |                         0 / 0 |
| Focused mdtest after Rust fix            | 25.05 s | 15.25 s |     39.12% |                         3 / 3 |
| Full semantic package tests              | 74.74 s | 49.95 s |     33.17% |                         2 / 2 |
| Rebuild CLI with its original features   | 24.83 s | 24.14 s |      2.78% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.42 s |  2.38 s |      1.77% |                         0 / 0 |
| Clippy with all targets and features     | 70.79 s | 26.32 s |     62.82% |                      209 / 41 |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 276.21–281.70 s for Rust and 178.26–185.82 s for Ohm. Initial CLI build medians are 108.35 s and 95.56 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.57 s |          88.58 s | 90.09 s | 86.93–90.15 s |               304 |                    87.87 s |
| Ohm + shared build                 |   1.82 s |          55.85 s | 57.67 s | 56.82–58.44 s |                80 |                    71.45 s |
| Ohm + shared build + trust opt-ins |   1.69 s |          50.82 s | 52.46 s | 51.74–53.04 s |                36 |                    72.03 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |   Total |   Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | ------: | ------------: | ----------------: | -------------------------: |
| Rust                               |   1.71 s |          90.49 s | 92.20 s | 91.67–94.67 s |               304 |                    88.62 s |
| Ohm + shared build                 |   1.78 s |          55.16 s | 57.27 s | 56.49–62.42 s |                80 |                    71.77 s |
| Ohm + shared build + trust opt-ins |   3.21 s |           6.31 s |  9.52 s |  9.17–10.45 s |                 5 |                    71.72 s |

The trusted Btrfs runs seed 2731 files, including 2693 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Genoa Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs rotate and reverse the three configurations; worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `d6c0dad5a710ae54b780893f8ee502f02e6fed5f`.

The [evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-6-777b898880f2) contains command logs, CPU traces, source and test checks, and excluded attempts. Its SHA-256 is `777b898880f27fba5dd5fe5638f780f970f52963b8bc028e5cd4ffcc9e76ad73`.
