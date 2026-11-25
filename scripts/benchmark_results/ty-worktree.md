# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-10 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-10 | Time saved |
| ------------------------ | ------------ | -------------- | ---------- |
| ty session               | 314.30 s     | 157.70 s       | 49.83%     |
| Worktree startup (ext4)  | 105.02 s     | 51.31 s        | 51.14%     |
| Worktree startup (Btrfs) | 114.87 s     | 56.79 s        | 50.56%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.54 s  | 0.65 s  | -20.84%    | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.35 s  | 0.37 s  | -5.97%     | 0 / 0                          |
| First failing focused mdtest             | 93.41 s | 56.95 s | 39.03%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.63 s  | 1.38 s  | 15.71%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 31.37 s | 12.72 s | 59.45%     | 3 / 3                          |
| Full semantic package tests              | 83.94 s | 46.46 s | 44.65%     | 2 / 2                          |
| Rebuild CLI with its original features   | 29.47 s | 12.86 s | 56.36%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.68 s  | 2.28 s  | 14.95%     | 0 / 0                          |
| Clippy with all targets and features     | 74.39 s | 21.08 s | 71.66%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 305.83–319.91 s for Rust and 151.05–163.33 s for Ohm. Initial CLI build medians are 117.76 s and 92.21 s. The command monitor observed overlapping compiler activity in 1 ext4 attempt and 0 Btrfs attempts. Each affected run restarted from a fresh target. The raw archives retain the partial timings and logs.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 1.88 s   | 103.05 s         | 105.02 s | 103.52–108.82 s | 304               | 102.44 s                   |
| Ohm + shared build                 | 2.00 s   | 55.19 s          | 57.20 s  | 56.57–57.77 s   | 80                | 70.13 s                    |
| Ohm + shared build + trust opt-ins | 2.10 s   | 49.46 s          | 51.31 s  | 51.21–56.23 s   | 36                | 72.03 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.25 s   | 112.84 s         | 114.87 s | 103.25–117.95 s | 304               | 105.50 s                   |
| Ohm + shared build                 | 2.22 s   | 60.89 s          | 62.89 s  | 61.91–64.48 s   | 80                | 70.73 s                    |
| Ohm + shared build + trust opt-ins | 4.43 s   | 52.36 s          | 56.79 s  | 53.41–57.00 s   | 15                | 69.84 s                    |

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
