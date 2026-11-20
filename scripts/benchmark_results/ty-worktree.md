# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-3 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-3 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 268.26 s     | 159.49 s      | 40.55%     |
| Worktree startup (ext4)  | 91.83 s      | 53.62 s       | 41.62%     |
| Worktree startup (Btrfs) | 98.30 s      | 57.35 s       | 41.67%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.38 s  | 0.40 s  | -5.32%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.21 s  | 0.19 s  | 11.09%     | 0 / 0                          |
| First failing focused mdtest             | 78.35 s | 58.85 s | 24.88%     | 116 / 116                      |
| Repeat after Markdown-only edit          | 1.31 s  | 1.22 s  | 6.78%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 24.28 s | 14.51 s | 40.25%     | 3 / 3                          |
| Full semantic package tests              | 74.41 s | 43.34 s | 41.76%     | 2 / 2                          |
| Rebuild CLI with its original features   | 23.85 s | 14.14 s | 40.70%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.04 s  | 2.08 s  | -2.01%     | 0 / 0                          |
| Clippy with all targets and features     | 62.37 s | 22.92 s | 63.25%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 265.51–271.29 s for Rust and 158.42–161.65 s for Ohm. Initial CLI build medians are 108.24 s and 91.35 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.05 s   | 90.78 s          | 91.83 s | 87.21–92.68 s | 304               | 88.78 s                    |
| Ohm + shared build                 | 1.37 s   | 54.81 s          | 56.18 s | 54.52–58.50 s | 80                | 68.18 s                    |
| Ohm + shared build + trust opt-ins | 1.43 s   | 52.19 s          | 53.62 s | 53.30–56.10 s | 36                | 68.97 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.20 s   | 97.10 s          | 98.30 s | 95.08–99.37 s | 304               | 97.54 s                    |
| Ohm + shared build                 | 1.35 s   | 58.78 s          | 60.12 s | 59.69–61.20 s | 80                | 75.71 s                    |
| Ohm + shared build + trust opt-ins | 3.96 s   | 53.39 s          | 57.35 s | 56.25–61.04 s | 15                | 74.44 s                    |

The trusted Btrfs runs seed 4355 files, including 4317 reflinked files. Each filesystem has its own stock comparison.

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
