# ty iteration and worktree startup

Stock Rust 1.99.0 and released Ohm 1.99.0-3, measured on the same Linux devbox. The session replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327); the worktree study measures creation and first validation after a warm parent.

## Results

| Workload                                                       | Rust 1.99.0 | Ohm 1.99.0-3 | Time saved |
| -------------------------------------------------------------- | ----------- | ------------ | ---------- |
| ty session                                                     | 347.60 s    | 265.85 s     | 23.52%     |
| Worktree startup, ext4: shared build                           | 109.46 s    | 72.43 s      | 33.83%     |
| Worktree startup, ext4: shared build + trust opt-ins           | 109.46 s    | 66.14 s      | 39.58%     |
| Worktree startup, Btrfs loopback: shared build                 | 109.31 s    | 73.34 s      | 32.91%     |
| Worktree startup, Btrfs loopback: shared build + trust opt-ins | 109.31 s    | 16.76 s      | 84.67%     |

Each value is the median of four complete session replays or three worktree runs per configuration and filesystem. The [JSON report](ty-worktree-1.99.0-3.json) retains every accepted sample, per-step timings, source identities, and audit summaries.

### Session commands

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

Ohm saves the most time on the first focused-test build, the full-package test step, and Clippy. The focused test after the Rust edit and the CLI rebuild are slower with Ohm. Both toolchains launch the same number of compiler processes for the build and test steps; Ohm launches more during Clippy. These counts do not explain the timing differences by themselves.

Compiler launches come from Cargo’s verbose execution logs. They describe driver invocations, not the amount of work performed by each invocation. The complete-session median includes edits and runner overhead; it is not the sum of the per-command medians.

Complete-session ranges: Rust 341.81–354.21 s; Ohm 263.09–270.10 s. Untimed baseline CLI build medians: Rust 131.95 s; Ohm 116.76 s.

The Markdown-only iteration launches no compiler on either toolchain. All replays run 975 semantic package tests and the same three focused test invocations, including the two expected failures.

Cargo and Nextest report the following breakdown for the full-package step. Cargo rounds long build durations to whole seconds.

| Toolchain | Reported build duration | Reported test execution |
| --------- | ----------------------- | ----------------------- |
| Rust      | 80.50 s                 | 16.47 s                 |
| Ohm       | 48.98 s                 | 18.65 s                 |

For the full-package step, Ohm’s reported build time falls from 80.50 s to 48.98 s, while test execution rises from 16.47 s to 18.65 s.

### Worktree startup

The ext4 runs did not seed worktree snapshots. The Btrfs study verifies copy-on-write support and successful snapshot seeding in every trusted Ohm run.

#### ext4

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.51 s   | 106.95 s         | 109.46 s | 108.35–109.96 s | 304               | 108.45 s                   |
| Ohm + shared build                 | 3.67 s   | 68.76 s          | 72.43 s  | 70.49–72.94 s   | 80                | 87.38 s                    |
| Ohm + shared build + trust opt-ins | 3.53 s   | 62.62 s          | 66.14 s  | 66.07–67.93 s   | 36                | 85.60 s                    |

#### Btrfs loopback

| Configuration                      | Creation | First validation | Total    | Total range     | Compiler launches | Untimed parent preparation |
| ---------------------------------- | -------- | ---------------- | -------- | --------------- | ----------------- | -------------------------- |
| Rust                               | 2.21 s   | 107.10 s         | 109.31 s | 107.95–111.63 s | 304               | 107.51 s                   |
| Ohm + shared build                 | 3.67 s   | 69.66 s          | 73.34 s  | 72.51–73.62 s   | 80                | 87.71 s                    |
| Ohm + shared build + trust opt-ins | 6.66 s   | 10.10 s          | 16.76 s  | 15.34–17.53 s   | 5                 | 87.50 s                    |

The trusted Btrfs runs seeded 2684 files, including 2646 reflinked files. The next Cargo command validates whether those artifacts can be reused.

The total is the median of each run’s creation-plus-validation time. Parent preparation warms the focused mdtest; it is paid before the new worktree is created.

## What the session measures

We warm the baseline `ty` executable, then replay nine commands and three recorded edits from [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327). The sequence reproduces the original diagnostics, adds and expands a failing Markdown regression, changes Rust source to fix it, runs the focused and full semantic tests, rebuilds the executable, compares 24 diagnostic results, and runs Clippy across the semantic package's targets and features.

The two failing test commands must return Nextest's expected failure status and contain the recorded diagnostics. Each completed replay must match the public PR's final source. The baseline and fixed executables must also produce the same 24 diagnostic results on both toolchains.

We preserve `opt-level = 1`, line-table debug information, disabled LTO, and the source's dependency profile overrides. The CLI, focused tests, and all-feature Clippy retain their different feature graphs. Snapshot mutation is disabled for both toolchains. A portable Python helper replaces the original Python launcher; copying the baseline executable remains part of its timed command.

Ohm uses a separate shared build directory and both procedural-macro and native-tool trust opt-ins. Each repetition starts with fresh artifacts. We exclude the initial CLI build from the session total and report it separately.

## What worktree startup measures

For each configuration, we build the focused `liskov.md` test in a fresh parent checkout. We then time worktree creation and the first execution of that same focused test in the child. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Every child has a private target directory. Ohm's parent and child share a separate registry build directory.

We measure stock Rust, Ohm with a shared build directory, and Ohm with that shared directory plus both trust opt-ins. The shared-build-only configuration leaves both trust switches disabled. Each configuration gets fresh parent, child, target, and shared directories. Parent preparation is excluded from the startup total and reported separately. Source checks between creation and validation are also outside that total.

The first study uses the devbox's ext4 filesystem. Ohm's creation logs show that no snapshots were seeded: ext4 lacks the required copy-on-write cloning. The second study uses an isolated 256 GiB Btrfs image backed by an ext4 file on the same devbox. A `cp --reflink=always` probe verifies cloning and checks that editing the clone leaves its source unchanged. All three configurations use that filesystem, and each trusted Ohm run must report successfully seeded, reflinked files. Compare toolchains within each filesystem; the two filesystem studies ran sequentially.

After timing, we locate the original test executable, change only the child's Markdown test data, and run that executable directly to require the expected failure. We then restore the child and require the same executable to pass. Its SHA-256 must remain unchanged across both checks; Cargo is not invoked during this validation. The parent's source must remain unchanged. All 18 children undergo this check, which verifies that reused test artifacts read the child's current test data.

## Measurement conditions

The measurements run on a 16-CPU AMD EPYC-Milan Linux devbox with eight Cargo jobs and checksum-pinned Nextest 0.9.140. Toolchain binaries come from the stock Rust and Ohm release archives. Cargo runs offline after dependencies have been fetched. Cargo emits verbose execution logs on both toolchains so we can count actual `rustc` and `clippy-driver` invocations; that logging overhead is included.

We run four session repetitions per toolchain, alternating order, and three worktree repetitions per configuration on each filesystem, rotating order. Tables compare medians; individual samples and ranges remain in the JSON report. Ranges describe these runs, not confidence intervals.

Each cell begins with six five-second quiet checks requiring at least 95% idle CPU, at most 0.5% I/O wait and 0.1% steal, no unrelated compiler, at most 1% CPU from other processes belonging to the benchmark user, and at least 60 GiB free. Continuous two-second monitoring covers parent preparation and timed work. It rejects unrelated compilers, more than 1% CPU used by other processes belonging to the benchmark user, a CPU-steal interval above 1%, a whole-cell average above 0.1% steal, and three consecutive intervals above 5% outside CPU excluding the recorded Falcon service. Falcon and other infrastructure services remain enabled, and their overhead remains in the timings. The outside-process CPU check includes kernel filesystem workers, so filesystem activity can also cause a retry. Rejected cells restart from fresh artifacts and remain in the evidence. Two earlier monitoring policies rejected short periods above 0.1% steal despite a low whole-cell average. We excluded both preliminary campaigns and restarted the complete comparison under the spike and whole-cell limits. The Btrfs study uses those same final monitoring rules.

These results compare two complete toolchains on these workloads. They do not isolate an individual Ohm optimization or measure the change from an earlier Ohm release. They are separate from the existing three-session headline aggregate, which uses different fixtures, machines, and logging settings. The worktree measurements report elapsed time on Linux, with no claim about APFS allocation.

## Evidence

The [raw evidence archive](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-3-828c752e72b6) retains all accepted and excluded attempts, command logs, CPU traces, the frozen harness, source checks, and all 18 child-worktree correctness checks. Its SHA-256 is `828c752e72b61aca3d3a660d2d3464304dddfbae9a69342182462a9d8ff4c08c`.

The fixture starts at [`4d6a7db78713`](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6) and reproduces [`e221f3e9b5b2`](https://github.com/astral-sh/ruff/commit/e221f3e9b5b22b81b0ce4e7c730ac1f5c990adf0). The measured harness is Ohm commit `6c64dbcdfb2cfccc095c0242687f7e14464cd1b8`.
