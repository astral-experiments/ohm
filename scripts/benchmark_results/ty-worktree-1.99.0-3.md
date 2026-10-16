# ty session and worktree startup

We compare stock Rust 1.99.0 with Ohm 1.99.0-3 on Linux. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); worktree startup measures creation and the first test run after the parent has built that test.

| Workload                 | Rust 1.99.0 | Ohm 1.99.0-3 | Time saved |
| ------------------------ | ----------- | ------------ | ---------- |
| ty session               | 347.60 s    | 265.85 s     | 23.52%     |
| Worktree startup (ext4)  | 109.46 s    | 66.14 s      | 39.58%     |
| Worktree startup (Btrfs) | 109.31 s    | 16.76 s      | 84.67%     |

These are medians of four session replays and three startup runs per configuration. Ohm uses a shared build directory and both trust opt-ins. Btrfs runs on a loopback filesystem backed by ext4.

## Session

The replay adds a failing Markdown test, expands it, applies the Rust fix, runs focused and package tests, rebuilds ty, checks its diagnostics, and runs Clippy. It keeps the original `opt-level = 1` and the different features used by the CLI, tests, and Clippy. The initial CLI build is excluded from the session total.

| Command                                  | Rust    | Ohm     | Time saved | Compiler launches: Rust / Ohm |
| ---------------------------------------- | ------- | ------- | ---------- | ----------------------------- |
| Build baseline CLI                       | 0.49 s  | 1.29 s  | -165.10%   | 0 / 0                         |
| Verify original diagnostics and save CLI | 0.45 s  | 0.52 s  | -14.67%    | 0 / 0                         |
| First failing focused mdtest             | 96.66 s | 74.44 s | 22.99%     | 116 / 116                     |
| Repeat after Markdown-only edit          | 1.69 s  | 2.28 s  | -34.83%    | 0 / 0                         |
| Focused mdtest after Rust fix            | 29.99 s | 31.54 s | -5.19%     | 3 / 3                         |
| Full semantic package tests              | 97.68 s | 68.63 s | 29.75%     | 2 / 2                         |
| Rebuild CLI with its original features   | 30.65 s | 33.16 s | -8.20%     | 6 / 6                         |
| Compare 24 diagnostic results            | 2.84 s  | 3.26 s  | -14.63%    | 0 / 0                         |
| All-target, all-feature Clippy           | 86.09 s | 47.82 s | 44.46%     | 209 / 286                     |

Ohm saves the most time on the first test build, package tests, and Clippy. The focused test after the Rust edit and the CLI rebuild are slower. The Markdown-only edit rebuilds nothing on either toolchain.

For the package tests, Cargo's reported build time falls from 80.50 s to 48.98 s, while Nextest's test execution rises from 16.47 s to 18.65 s. Compiler counts describe driver launches, not the work each driver performs.

Complete-session ranges are 341.81–354.21 s for Rust and 263.09–270.10 s for Ohm. Initial CLI build medians are 131.95 s and 116.76 s. Per-command medians need not sum to the session median.

## Worktree startup

We build the focused `liskov.md` test in a parent checkout, then time worktree creation and the first run of that test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Each child has its own target directory. Parent preparation is excluded from the total.

### ext4

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.51 s   | 106.95 s         | 109.46 s | 108.35–109.96 s | 304               | 108.45 s                   |
| Ohm + shared build                 | 3.67 s   | 68.76 s          | 72.43 s  | 70.49–72.94 s   | 80                | 87.38 s                    |
| Ohm + shared build + trust opt-ins | 3.53 s   | 62.62 s          | 66.14 s  | 66.07–67.93 s   | 36                | 85.60 s                    |

### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.21 s   | 107.10 s         | 109.31 s | 107.95–111.63 s | 304               | 107.51 s                   |
| Ohm + shared build                 | 3.67 s   | 69.66 s          | 73.34 s  | 72.51–73.62 s   | 80                | 87.71 s                    |
| Ohm + shared build + trust opt-ins | 6.66 s   | 10.10 s          | 16.76 s  | 15.34–17.53 s   | 5                 | 87.50 s                    |

The trusted Btrfs runs seed 2684 files, including 2646 reflinked files. ext4 cannot clone the snapshots, so its improvement comes from shared-build reuse and the toolchain. Each filesystem has its own stock comparison.

## Configuration

- 16-CPU AMD EPYC-Milan Linux devbox, eight Cargo jobs, Nextest 0.9.140.
- `opt-level = 1`, line-table debug information, LTO off, and the source's dependency profile overrides.
- Cargo runs offline with verbose logging on both toolchains.
- The session and trusted startup runs set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`.
- Each repetition starts with fresh artifacts. Toolchain order alternates for sessions and rotates for startup runs.

Runs wait for an idle host and restart if CPU monitoring detects interference. The [JSON report](ty-worktree-1.99.0-3.json) records the thresholds, samples, source checks, and rejected attempts. These measurements compare complete toolchains; they do not isolate individual optimizations.

## Reproduce

See the [session](../session_replays/README.md#ty-diagnostic-suppression-session) and [worktree startup](../session_replays/README.md#worktree-startup) commands. The fixture starts at [`4d6a7db78713`](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [`e221f3e9b5b2`](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `6c64dbcdfb2cfccc095c0242687f7e14464cd1b8`.

The [evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-3-828c752e72b6) contains command logs, CPU traces, source and test checks, and excluded attempts. Its SHA-256 is `828c752e72b61aca3d3a660d2d3464304dddfbae9a69342182462a9d8ff4c08c`.
