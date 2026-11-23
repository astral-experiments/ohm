# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-7 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-7 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 286.70 s     | 142.01 s      | 50.47%     |
| Worktree startup (ext4)  | 96.19 s      | 48.88 s       | 49.19%     |
| Worktree startup (Btrfs) | 101.62 s     | 53.47 s       | 47.38%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.45 s  | 0.44 s  | 3.54%      | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.32 s  | 0.27 s  | 15.21%     | 0 / 0                          |
| First failing focused mdtest             | 83.84 s | 52.40 s | 37.50%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.47 s  | 1.18 s  | 19.47%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 25.07 s | 11.18 s | 55.40%     | 3 / 3                          |
| Full semantic package tests              | 77.20 s | 41.55 s | 46.17%     | 2 / 2                          |
| Rebuild CLI with its original features   | 25.76 s | 11.21 s | 56.48%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.32 s  | 2.01 s  | 13.39%     | 0 / 0                          |
| Clippy with all targets and features     | 67.62 s | 19.89 s | 70.59%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 280.96–292.70 s for Rust and 139.90–145.54 s for Ohm. Initial CLI build medians are 113.06 s and 88.74 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.68 s   | 94.53 s          | 96.19 s | 93.25–97.83 s | 304               | 92.78 s                    |
| Ohm + shared build                 | 1.73 s   | 52.48 s          | 54.21 s | 53.03–55.99 s | 80                | 66.05 s                    |
| Ohm + shared build + trust opt-ins | 1.85 s   | 47.07 s          | 48.88 s | 48.76–51.55 s | 36                | 65.68 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.83 s   | 99.77 s          | 101.62 s | 92.36–102.36 s | 304               | 96.44 s                    |
| Ohm + shared build                 | 2.09 s   | 53.34 s          | 55.43 s  | 54.65–65.22 s  | 80                | 67.15 s                    |
| Ohm + shared build + trust opt-ins | 4.38 s   | 48.94 s          | 53.47 s  | 50.65–53.84 s  | 15                | 67.20 s                    |

The trusted Btrfs runs seed 5054 files, including 5016 reflinked files. Each filesystem has its own stock comparison.

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
