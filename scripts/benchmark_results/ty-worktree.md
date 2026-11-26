# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-12 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-12 | Time saved |
| ------------------------ | ------------ | -------------- | ---------- |
| ty session               | 299.49 s     | 144.72 s       | 51.68%     |
| Worktree startup (ext4)  | 93.93 s      | 48.70 s        | 48.15%     |
| Worktree startup (Btrfs) | 114.72 s     | 55.79 s        | 51.37%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.44 s  | 0.50 s  | -14.03%    | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.32 s  | 0.29 s  | 7.80%      | 0 / 0                          |
| First failing focused mdtest             | 82.77 s | 54.00 s | 34.76%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.35 s  | 1.42 s  | -4.94%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 25.52 s | 12.01 s | 52.96%     | 3 / 3                          |
| Full semantic package tests              | 79.60 s | 40.45 s | 49.18%     | 2 / 2                          |
| Rebuild CLI with its original features   | 28.65 s | 11.30 s | 60.55%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.42 s  | 2.08 s  | 14.03%     | 0 / 0                          |
| Clippy with all targets and features     | 73.09 s | 19.41 s | 73.44%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 284.18–317.05 s for Rust and 134.58–155.37 s for Ohm. Initial CLI build medians are 113.28 s and 85.63 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.73 s   | 92.17 s          | 93.93 s | 91.64–97.48 s | 304               | 95.01 s                    |
| Ohm + shared build                 | 2.06 s   | 50.06 s          | 52.12 s | 49.20–52.61 s | 80                | 63.61 s                    |
| Ohm + shared build + trust opt-ins | 1.74 s   | 46.97 s          | 48.70 s | 46.84–49.01 s | 36                | 61.93 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.15 s   | 112.28 s         | 114.72 s | 100.53–123.38 s | 304               | 117.90 s                   |
| Ohm + shared build                 | 2.17 s   | 56.40 s          | 58.61 s  | 52.02–59.37 s   | 80                | 67.34 s                    |
| Ohm + shared build + trust opt-ins | 4.55 s   | 50.89 s          | 55.79 s  | 50.25–57.88 s   | 15                | 63.68 s                    |

The trusted Btrfs runs seed 5114 files, including 5076 reflinked files. Each filesystem has its own stock comparison.

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
