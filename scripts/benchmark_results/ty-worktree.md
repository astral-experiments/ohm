# ty session and worktree startup

We compared stock Rust 1.99.0 with Ohm 1.99.0-9 on Linux. The session replays a ty bug fix. The worktree study measures how long it takes to create a child worktree and run a test that the parent has already built. [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-9 | Time saved |
| ------------------------ | ----------: | -----------: | ---------: |
| ty session               |    358.42 s |     224.74 s |     37.30% |
| Worktree startup (ext4)  |    130.66 s |      69.95 s |     46.46% |
| Worktree startup (Btrfs) |    127.42 s |      13.86 s |     89.12% |

The session result is the mean of four replays. Startup results are medians of three runs per configuration. The Ohm rows above use a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  |    Rust |     Ohm | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------: | ------: | ---------: | ----------------------------: |
| Build unchanged baseline CLI             |  0.56 s |  0.67 s |    -18.89% |                         0 / 0 |
| Verify original diagnostics and save CLI |  0.47 s |  0.39 s |     16.65% |                         0 / 0 |
| First failing focused mdtest             | 99.84 s | 74.23 s |     25.65% |                     116 / 116 |
| Repeat after Markdown-only edit          |  1.77 s |  1.63 s |      8.26% |                         0 / 0 |
| Focused mdtest after Rust fix            | 31.11 s | 30.57 s |      1.75% |                         3 / 3 |
| Full semantic package tests              | 95.98 s | 60.59 s |     36.87% |                         2 / 2 |
| Rebuild CLI with its original features   | 30.35 s | 19.30 s |     36.43% |                         6 / 6 |
| Compare 24 diagnostic results            |  2.95 s |  2.92 s |      1.01% |                         0 / 0 |
| Clippy with all targets and features     | 94.34 s | 32.64 s |     65.41% |                      209 / 41 |

Command timings are medians. The compiler counts measure driver launches, which can do different amounts of work. We compute each complete session total before taking its mean.

Session ranges are 353.32–365.39 s for Rust and 223.19–227.03 s for Ohm. Initial CLI build medians are 135.87 s and 116.94 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add` and Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.60 s |         129.02 s | 130.66 s | 111.72–131.07 s |               304 |                   125.23 s |
| Ohm + shared build                 |   1.69 s |          72.15 s |  73.86 s |   70.84–75.96 s |                80 |                    91.92 s |
| Ohm + shared build + trust opt-ins |   1.87 s |          68.40 s |  69.95 s |   66.66–76.67 s |                36 |                    93.12 s |

### Btrfs loopback

| Configuration                      | Creation | First validation |    Total |     Total range | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------: | ---------------: | -------: | --------------: | ----------------: | -------------------------: |
| Rust                               |   1.89 s |         125.53 s | 127.42 s | 126.32–132.18 s |               304 |                   125.88 s |
| Ohm + shared build                 |   2.12 s |          78.53 s |  80.65 s |   76.54–90.79 s |                80 |                    97.22 s |
| Ohm + shared build + trust opt-ins |   3.55 s |           8.77 s |  13.86 s |   12.32–18.70 s |                 5 |                    97.82 s |

The trusted Btrfs runs seed 2741 files, including 2703 reflinked files. Each filesystem has its own stock comparison.

After timing, we change only each child’s Markdown regression and run its original test executable directly. All 18 children fail with the changed test data and pass after restoration. The parent sources and executable hashes remain unchanged.

## Configuration

- 32-CPU AMD EPYC-Milan Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Session runs alternate the order of stock and Ohm. Worktree configurations rotate.

Runs wait for an idle host and restart if CPU monitoring detects interference. These measurements compare the complete stock and Ohm toolchains. The report records the thresholds, samples, source checks, and rejected attempts. [Full ty results](ty-worktree.json)

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [4d6a7db78713](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [e221f3e9b5b2](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677`.
