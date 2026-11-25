# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-11 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-11 | Time saved |
| ------------------------ | ------------ | -------------- | ---------- |
| ty session               | 289.66 s     | 143.05 s       | 50.61%     |
| Worktree startup (ext4)  | 95.72 s      | 48.81 s        | 49.01%     |
| Worktree startup (Btrfs) | 114.03 s     | 52.81 s        | 53.69%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.47 s  | 0.42 s  | 10.84%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.39 s  | 0.29 s  | 25.82%     | 0 / 0                          |
| First failing focused mdtest             | 83.76 s | 52.20 s | 37.68%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.39 s  | 1.25 s  | 9.96%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 27.14 s | 10.86 s | 59.98%     | 3 / 3                          |
| Full semantic package tests              | 78.68 s | 42.26 s | 46.29%     | 2 / 2                          |
| Rebuild CLI with its original features   | 26.05 s | 11.43 s | 56.13%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.19 s  | 2.17 s  | 1.08%      | 0 / 0                          |
| Clippy with all targets and features     | 63.83 s | 19.87 s | 68.87%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 276.46–307.17 s for Rust and 137.40–148.99 s for Ohm. Initial CLI build medians are 111.65 s and 86.45 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.66 s   | 94.07 s          | 95.72 s | 95.60–100.13 s | 304               | 92.45 s                    |
| Ohm + shared build                 | 1.77 s   | 50.62 s          | 52.30 s | 51.59–53.71 s  | 80                | 63.52 s                    |
| Ohm + shared build + trust opt-ins | 1.74 s   | 47.09 s          | 48.81 s | 47.69–49.68 s  | 36                | 64.74 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.99 s   | 112.03 s         | 114.03 s | 99.63–114.31 s | 304               | 98.86 s                    |
| Ohm + shared build                 | 2.12 s   | 56.32 s          | 58.57 s  | 50.91–61.81 s  | 80                | 68.08 s                    |
| Ohm + shared build + trust opt-ins | 4.23 s   | 48.64 s          | 52.81 s  | 51.23–56.97 s  | 15                | 68.97 s                    |

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
