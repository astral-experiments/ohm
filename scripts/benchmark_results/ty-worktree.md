# ty session and worktree startup

We measured stock Rust 1.100.0 and published Ohm 1.100.0-8 on Linux. The session replays a fix to ty’s override diagnostics. Worktree startup covers creation and the first test run after the parent has built that test. [Replayed change](https://github.com/astral-sh/ruff/pull/29327)

| Workload                 | Rust 1.100.0 | Ohm 1.100.0-8 | Time saved |
| ------------------------ | ------------ | ------------- | ---------- |
| ty session               | 306.59 s     | 155.75 s      | 49.20%     |
| Worktree startup (ext4)  | 91.41 s      | 50.72 s       | 44.51%     |
| Worktree startup (Btrfs) | 111.44 s     | 53.85 s       | 51.68%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches (Rust / Ohm) |
| ---------------------------------------- | ------- | ------- | ---------- | ------------------------------ |
| Build unchanged baseline CLI             | 0.64 s  | 0.69 s  | -8.69%     | 0 / 0                          |
| Verify original diagnostics and save CLI | 0.44 s  | 0.36 s  | 18.02%     | 0 / 0                          |
| First failing focused mdtest             | 92.33 s | 56.06 s | 39.29%     | 116 / 117                      |
| Repeat after Markdown-only edit          | 1.40 s  | 1.48 s  | -5.23%     | 0 / 0                          |
| Focused mdtest after Rust fix            | 26.26 s | 13.01 s | 50.45%     | 3 / 3                          |
| Full semantic package tests              | 86.47 s | 47.43 s | 45.14%     | 2 / 2                          |
| Rebuild CLI with its original features   | 27.61 s | 13.87 s | 49.75%     | 6 / 6                          |
| Compare 24 diagnostic results            | 2.34 s  | 2.06 s  | 11.83%     | 0 / 0                          |
| Clippy with all targets and features     | 65.88 s | 20.03 s | 69.60%     | 209 / 41                       |

Command timings are medians. Each compiler count records a driver launch; the amount of work per launch can differ. We compute each complete session total before taking its mean.

Session ranges are 293.87–331.36 s for Rust and 144.01–162.53 s for Ohm. Initial CLI build medians are 120.32 s and 92.89 s. The command monitor observed overlapping compiler activity in 1 ext4 attempt and 0 Btrfs attempts. Each affected run restarted from a fresh target. The raw archives retain the partial timings and logs.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total. We compute each complete startup time before taking its median.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.77 s   | 89.57 s          | 91.41 s | 91.10–99.16 s | 304               | 92.90 s                    |
| Ohm + shared build                 | 1.68 s   | 52.40 s          | 54.00 s | 50.94–55.20 s | 80                | 64.44 s                    |
| Ohm + shared build + trust opt-ins | 1.82 s   | 48.90 s          | 50.72 s | 47.99–51.78 s | 36                | 65.39 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.01 s   | 109.43 s         | 111.44 s | 104.31–117.99 s | 304               | 103.59 s                   |
| Ohm + shared build                 | 2.09 s   | 59.43 s          | 61.52 s  | 56.77–62.40 s   | 80                | 70.09 s                    |
| Ohm + shared build + trust opt-ins | 5.15 s   | 48.20 s          | 53.85 s  | 51.76–58.04 s   | 15                | 67.53 s                    |

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
