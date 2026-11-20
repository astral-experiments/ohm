# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-2 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-2 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 291.26 s     | 164.14 s      | 43.64%     |
| Worktree startup (ext4)  | 95.29 s      | 57.45 s       | 39.71%     |
| Worktree startup (Btrfs) | 98.97 s      | 62.55 s       | 36.80%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.46 s  | 0.43 s  | 6.76%      | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.32 s  | 0.30 s  | 6.86%      | 0 / 0                          |
| First failing focused mdtest             | 85.02 s | 59.53 s | 29.98%     | 116 / 116                      |
| Repeat after Markdown-only edit          | 1.40 s  | 1.27 s  | 9.58%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 25.84 s | 14.77 s | 42.87%     | 3 / 3                          |
| Full semantic package tests              | 79.51 s | 45.64 s | 42.60%     | 2 / 2                          |
| Rebuild CLI with its original features   | 26.94 s | 14.75 s | 45.24%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.42 s  | 2.31 s  | 4.89%      | 0 / 0                          |
| Clippy with all targets and features     | 69.23 s | 24.17 s | 65.08%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 276.54–302.42 s for Rust and 161.92–165.18 s for Ohm. Initial CLI build medians are 113.74 s and 95.60 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.20 s   | 94.10 s          | 95.29 s | 94.37–95.69 s | 304               | 94.96 s                    |
| Ohm + shared build                 | 1.41 s   | 57.75 s          | 59.18 s | 54.84–61.83 s | 80                | 71.56 s                    |
| Ohm + shared build + trust opt-ins | 1.40 s   | 56.07 s          | 57.45 s | 54.54–59.96 s | 36                | 73.52 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total   | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.57 s   | 97.40 s          | 98.97 s | 94.76–118.62 s | 304               | 103.95 s                   |
| Ohm + shared build                 | 1.50 s   | 62.10 s          | 63.81 s | 63.43–66.57 s  | 80                | 74.39 s                    |
| Ohm + shared build + trust opt-ins | 4.75 s   | 57.25 s          | 62.55 s | 61.99–63.45 s  | 15                | 75.31 s                    |

The trusted Btrfs runs seed 4439 files, including 4401 reflinked files. Each filesystem has its own stock comparison.

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
