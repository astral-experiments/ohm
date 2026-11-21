# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-5 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-5 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 287.84 s     | 159.31 s      | 44.65%     |
| Worktree startup (ext4)  | 99.53 s      | 53.44 s       | 46.31%     |
| Worktree startup (Btrfs) | 100.84 s     | 58.77 s       | 41.73%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.39 s  | 0.44 s  | -11.78%    | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.31 s  | 0.29 s  | 7.67%      | 0 / 0                          |
| First failing focused mdtest             | 83.19 s | 57.58 s | 30.78%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.41 s  | 1.26 s  | 10.76%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 26.14 s | 13.37 s | 48.85%     | 3 / 3                          |
| Full semantic package tests              | 81.57 s | 45.05 s | 44.77%     | 2 / 2                          |
| Rebuild CLI with its original features   | 25.11 s | 13.21 s | 47.39%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.24 s  | 2.11 s  | 5.87%      | 0 / 0                          |
| Clippy with all targets and features     | 66.12 s | 24.12 s | 63.51%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 281.82–296.15 s for Rust and 155.10–163.58 s for Ohm. Initial CLI build medians are 115.57 s and 92.49 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.72 s   | 97.81 s          | 99.53 s | 98.26–100.33 s | 304               | 94.49 s                    |
| Ohm + shared build                 | 1.74 s   | 57.02 s          | 58.76 s | 53.67–60.02 s  | 80                | 67.42 s                    |
| Ohm + shared build + trust opt-ins | 1.77 s   | 51.63 s          | 53.44 s | 52.20–59.06 s  | 36                | 69.05 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.93 s   | 98.79 s          | 100.84 s | 98.35–107.81 s | 304               | 107.51 s                   |
| Ohm + shared build                 | 2.00 s   | 61.93 s          | 63.73 s  | 61.22–70.66 s  | 80                | 72.12 s                    |
| Ohm + shared build + trust opt-ins | 4.35 s   | 54.41 s          | 58.77 s  | 57.23–60.68 s  | 15                | 71.42 s                    |

The trusted Btrfs runs seed 5179 files, including 5141 reflinked files. Each filesystem has its own stock comparison.

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
