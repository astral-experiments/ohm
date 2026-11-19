# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-1 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-1 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 290.45 s     | 182.60 s      | 37.13%     |
| Worktree startup (ext4)  | 90.75 s      | 58.36 s       | 35.70%     |
| Worktree startup (Btrfs) | 119.20 s     | 63.61 s       | 46.64%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.61 s  | 0.46 s  | 24.21%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.45 s  | 0.36 s  | 19.13%     | 0 / 0                          |
| First failing focused mdtest             | 86.72 s | 64.25 s | 25.90%     | 116 / 116                      |
| Repeat after Markdown-only edit          | 1.34 s  | 1.32 s  | 1.16%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 27.37 s | 16.68 s | 39.03%     | 3 / 3                          |
| Full semantic package tests              | 79.20 s | 50.67 s | 36.03%     | 2 / 2                          |
| Rebuild CLI with its original features   | 27.31 s | 16.75 s | 38.66%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.33 s  | 2.11 s  | 9.27%      | 0 / 0                          |
| Clippy with all targets and features     | 63.38 s | 26.44 s | 58.29%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 274.22–303.10 s for Rust and 173.13–194.28 s for Ohm. Initial CLI build medians are 117.12 s and 102.43 s. The command monitor observed overlapping compiler activity in 1 ext4 attempt and 1 Btrfs attempt. Each affected run restarted from a fresh target. The raw archives retain the partial timings and logs.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.11 s   | 89.77 s          | 90.75 s | 89.76–102.93 s | 304               | 99.56 s                    |
| Ohm + shared build                 | 1.26 s   | 63.68 s          | 64.94 s | 60.23–65.39 s  | 80                | 77.17 s                    |
| Ohm + shared build + trust opt-ins | 1.51 s   | 57.07 s          | 58.36 s | 55.66–64.63 s  | 36                | 78.05 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 1.45 s   | 117.56 s         | 119.20 s | 107.11–126.84 s | 304               | 103.46 s                   |
| Ohm + shared build                 | 1.64 s   | 66.61 s          | 68.26 s  | 66.94–71.67 s   | 80                | 85.51 s                    |
| Ohm + shared build + trust opt-ins | 4.10 s   | 60.48 s          | 63.61 s  | 63.31–68.73 s   | 15                | 82.37 s                    |

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
