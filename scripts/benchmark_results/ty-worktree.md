# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-5 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-5 | Time saved |
| ------------------------ | ----------- | ------------ | ---------- |
| ty session               | 287.99 s    | 189.85 s     | 34.08%     |
| Worktree startup (ext4)  | 90.26 s     | 54.06 s      | 40.11%     |
| Worktree startup (Btrfs) | 93.42 s     | 13.41 s      | 85.65%     |

The session result is the mean of four replays; startup results are medians of three runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------- | ------- | ---------- | ----------------------------- |
| Build unchanged baseline CLI             | 0.39 s  | 1.01 s  | -162.03%   | 0 / 0                         |
| Verify original diagnostics and save CLI | 0.84 s  | 0.68 s  | 19.11%     | 0 / 0                         |
| First failing focused mdtest             | 81.14 s | 61.64 s | 24.03%     | 116 / 116                     |
| Repeat after Markdown-only edit          | 1.67 s  | 1.86 s  | -11.72%    | 0 / 0                         |
| Focused mdtest after Rust fix            | 26.42 s | 17.82 s | 32.56%     | 3 / 3                         |
| Full semantic package tests              | 75.27 s | 49.69 s | 33.98%     | 2 / 2                         |
| Rebuild CLI with its original features   | 25.51 s | 21.00 s | 17.66%     | 6 / 6                         |
| Compare 24 diagnostic results            | 2.50 s  | 3.03 s  | -21.31%    | 0 / 0                         |
| Clippy with all targets and features     | 71.55 s | 32.31 s | 54.85%     | 209 / 41                      |

Command timings are medians. Compiler counts describe driver launches, not the work each driver performs. The edit to Markdown test data rebuilds nothing on either toolchain.

Session ranges are 282.11–295.77 s for Rust and 186.81–192.23 s for Ohm. Initial CLI build medians are 112.33 s and 102.10 s.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total.

### ext4

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.53 s   | 88.70 s          | 90.26 s | 89.90–91.03 s | 304               | 91.73 s                    |
| Ohm + shared build                 | 1.58 s   | 57.61 s          | 59.19 s | 57.87–62.50 s | 80                | 72.25 s                    |
| Ohm + shared build + trust opt-ins | 1.71 s   | 52.41 s          | 54.06 s | 53.77–54.27 s | 36                | 71.36 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total   | Total range   | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | ------- | ------------- | ----------------- | -------------------------- |
| Rust                               | 1.63 s   | 92.06 s          | 93.42 s | 90.12–99.50 s | 304               | 90.36 s                    |
| Ohm + shared build                 | 1.66 s   | 58.79 s          | 60.60 s | 60.19–63.59 s | 80                | 71.96 s                    |
| Ohm + shared build + trust opt-ins | 4.10 s   | 9.57 s           | 13.41 s | 12.76–13.66 s | 5                 | 72.57 s                    |

The trusted Btrfs runs seed 2733 files, including 2695 reflinked files. The ext4 runs use shared build state without cloning snapshots. Each filesystem has its own stock comparison.

## Configuration

- 32-CPU AMD EPYC-Genoa Processor Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Toolchain order alternates for sessions and rotates for startup runs.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations or changes between Ohm releases.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [`4d6a7db78713`](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [`e221f3e9b5b2`](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `31689f052811f815de715ba575386d92a0f40c4b`.

The [evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-5-80d5ffedf5ae) contains command logs, CPU traces, source and test checks, and excluded attempts. Its SHA-256 is `80d5ffedf5ae59cdf0ff603e8e346b2a275420eaba555c5b1099512eeb92ccf9`.
