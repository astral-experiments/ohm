# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-6 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-6 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 303.94 s     | 164.79 s      | 45.78%     |
| Worktree startup (ext4)  | 101.63 s     | 54.51 s       | 46.36%     |
| Worktree startup (Btrfs) | 101.68 s     | 58.39 s       | 42.57%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.52 s  | 0.77 s  | -47.57%    | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.33 s  | 0.34 s  | -2.86%     | 0 / 0                          |
| First failing focused mdtest             | 88.28 s | 60.85 s | 31.07%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.54 s  | 1.52 s  | 1.58%      | 0 / 0                          |
| Focused mdtest after Rust fix            | 27.73 s | 13.66 s | 50.74%     | 3 / 3                          |
| Full semantic package tests              | 90.24 s | 46.45 s | 48.53%     | 2 / 2                          |
| Rebuild CLI with its original features   | 27.74 s | 13.63 s | 50.86%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.50 s  | 2.07 s  | 16.95%     | 0 / 0                          |
| Clippy with all targets and features     | 65.53 s | 21.98 s | 66.46%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 293.83–311.04 s for Rust and 159.01–172.13 s for Ohm. Initial CLI build medians are 121.65 s and 97.25 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 1.79 s   | 99.88 s          | 101.63 s | 95.74–101.67 s | 304               | 95.88 s                    |
| Ohm + shared build                 | 1.84 s   | 51.25 s          | 53.02 s  | 52.82–58.51 s  | 80                | 69.68 s                    |
| Ohm + shared build + trust opt-ins | 1.89 s   | 52.58 s          | 54.51 s  | 49.78–57.51 s  | 36                | 70.32 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range    | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | -------------- | ----------------- | -------------------------- |
| Rust                               | 2.29 s   | 99.39 s          | 101.68 s | 98.54–121.80 s | 304               | 114.41 s                   |
| Ohm + shared build                 | 2.02 s   | 57.10 s          | 59.34 s  | 57.49–61.24 s  | 80                | 72.89 s                    |
| Ohm + shared build + trust opt-ins | 4.87 s   | 53.52 s          | 58.39 s  | 57.03–65.78 s  | 15                | 74.38 s                    |

The trusted Btrfs runs seed 5162 files, including 5124 reflinked files. Each filesystem has its own stock comparison.

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
