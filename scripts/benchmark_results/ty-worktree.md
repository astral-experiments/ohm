# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-4 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-4 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 306.21 s     | 169.57 s      | 44.62%     |
| Worktree startup (ext4)  | 100.27 s     | 55.65 s       | 44.50%     |
| Worktree startup (Btrfs) | 119.86 s     | 60.60 s       | 49.44%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.54 s  | 0.48 s  | 10.84%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.36 s  | 0.29 s  | 17.62%     | 0 / 0                          |
| First failing focused mdtest             | 89.61 s | 59.69 s | 33.39%     | 116 / 116                      |
| Repeat after Markdown-only edit          | 1.54 s  | 1.46 s  | 5.45%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 27.24 s | 15.31 s | 43.82%     | 3 / 3                          |
| Full semantic package tests              | 84.54 s | 47.10 s | 44.29%     | 2 / 2                          |
| Rebuild CLI with its original features   | 27.85 s | 15.88 s | 42.97%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.45 s  | 2.27 s  | 7.41%      | 0 / 0                          |
| Clippy with all targets and features     | 71.18 s | 25.92 s | 63.58%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 299.58–313.70 s for Rust and 160.59–178.30 s for Ohm. Initial CLI build medians are 119.78 s and 93.47 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.82 s   | 98.44 s          | 100.27 s | 95.34–106.73 s | 304               | 101.18 s                   |
| Ohm + shared build                 | 1.92 s   | 56.27 s          | 58.06 s  | 56.79–58.78 s  | 80                | 73.53 s                    |
| Ohm + shared build + trust opt-ins | 1.97 s   | 53.68 s          | 55.65 s  | 54.97–57.11 s  | 36                | 72.97 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.21 s   | 117.79 s         | 119.86 s | 114.95–124.79 s | 304               | 113.41 s                   |
| Ohm + shared build                 | 2.11 s   | 56.93 s          | 59.12 s  | 55.81–62.04 s   | 80                | 74.24 s                    |
| Ohm + shared build + trust opt-ins | 4.80 s   | 55.80 s          | 60.60 s  | 58.51–67.93 s   | 15                | 75.00 s                    |

The trusted Btrfs runs seed 4382 files, including 4344 reflinked files. Each filesystem has its own stock comparison.

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
