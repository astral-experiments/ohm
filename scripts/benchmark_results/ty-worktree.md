# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-13 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-13 | Time saved |
| ------------------------ | ------------ | -------------- | ---------- |
| ty session               | 290.51 s     | 143.86 s       | 50.48%     |
| Worktree startup (ext4)  | 91.44 s      | 46.76 s        | 48.87%     |
| Worktree startup (Btrfs) | 96.44 s      | 47.54 s        | 50.70%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.38 s  | 0.40 s  | -4.56%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.30 s  | 0.26 s  | 14.37%     | 0 / 0                          |
| First failing focused mdtest             | 80.99 s | 52.42 s | 35.27%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.56 s  | 1.29 s  | 17.50%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 26.04 s | 12.22 s | 53.05%     | 3 / 3                          |
| Full semantic package tests              | 82.15 s | 41.33 s | 49.69%     | 2 / 2                          |
| Rebuild CLI with its original features   | 25.77 s | 11.75 s | 54.40%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.41 s  | 2.23 s  | 7.63%      | 0 / 0                          |
| Clippy with all targets and features     | 67.96 s | 20.02 s | 70.54%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 266.53–315.11 s for Rust and 132.54–154.49 s for Ohm. Initial CLI build medians are 107.27 s and 83.20 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.57 s   | 89.72 s          | 91.44 s | 89.71–93.03 s | 304               | 88.65 s                    |
| Ohm + shared build                 | 1.76 s   | 46.85 s          | 48.61 s | 48.20–50.07 s | 80                | 59.96 s                    |
| Ohm + shared build + trust opt-ins | 1.81 s   | 44.99 s          | 46.76 s | 46.20–47.50 s | 36                | 59.97 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.66 s   | 94.78 s          | 96.44 s | 91.26–98.80 s | 304               | 94.70 s                    |
| Ohm + shared build                 | 1.90 s   | 49.05 s          | 50.95 s | 50.34–51.28 s | 80                | 62.01 s                    |
| Ohm + shared build + trust opt-ins | 3.91 s   | 43.59 s          | 47.54 s | 47.05–47.56 s | 15                | 61.22 s                    |

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
