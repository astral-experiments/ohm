# Real development-session replays

`scripts/replay_sessions.py` compares stock Rust and Ohm by replaying recorded
development sessions instead of isolated synthetic edits. Each fixture records
an actual session, exact public Git revisions, real source changes, and the
Cargo commands observed between those changes.

The bundled scenarios cover:

- Ruff/ty: recursive attribute inference changes, focused mdtests, Clippy,
  formatting, and package-wide tests.
- uv: the PyPI Simple API JSON parser, parser and registry-client tests,
  Clippy, and a localhost-only installation test.
- Codex: a publicly exported TUI rendering change, focused nextest workflows,
  strict Clippy, and the full TUI package. No private Codex source is required.

Run all three scenarios against existing repository checkouts:

```sh
ulimit -n 65536
install -d -m 700 /tmp/ohm-r8
export TMPDIR=/tmp/ohm-r8
python3 scripts/replay_sessions.py \
  --upstream 1.98.0 \
  --ohm ohm-1.98.0-8 \
  --scenario scripts/session_replays/ruff-rust-1.98.json \
  --scenario scripts/session_replays/codex-stable-goal-accounting.json \
  --source-path ruff=/path/to/ruff \
  --source-path uv=/path/to/uv \
  --source-path codex=/path/to/codex \
  --output-dir /tmp/ohm-real-session-benchmarks-r8 \
  --jobs 8 \
  --repetitions 2 \
  --require-idle
```

Use a real, private short temporary directory for the Codex replay, as above,
not a symlink to a longer path. Two existing tests depend on temporary-path
length or its encoded representation. The revision 8 measurements used
`TMPDIR=/tmp/ohm-r8` for both compilers and all three projects; use a fresh output
directory when changing that environment.

Source checkouts are never edited. The runner creates private Git mirrors and
detached worktrees, applies real commit-to-commit patches, and gives each
toolchain its own stable target directory. Baseline warmups populate each
toolchain's target before timed edits begin, making the comparison resemble an
already-active development session. Use `--no-warmup` to measure cold-start
sessions instead. If a public development branch has since been rebased or
deleted, missing replay commits are fetched by their exact pinned full SHAs.

The Ohm replay configuration explicitly enables a separate shared build directory
and `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all`. This existing developer opt-in trusts
authenticated registry procedural macros beyond the audited default and is
potentially unsound; these results do not measure packaged defaults alone.

The Codex example selects the separate
[`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture.
It preserves the original source revisions, three timed edits, commands, and
the 11 previously published host-sensitive/flaky-test exclusions. A small
[test-only patch](patches/codex-safety-retry-goal-accounting.patch) replaces an
assumption that goal elapsed time stays at exactly 12 seconds with lower and
upper bounds derived from actual elapsed wall time. Both source and inherited
goals must account for the known-active interval without exceeding the enclosing
duration. Exact token, history, and goal-continuation checks remain unchanged;
no tests or compiler optimizations are disabled by the patch. The original
`codex.json` fixture and historical measurements remain unchanged.

Fixtures can declare hash-pinned `setup_patches` for existing text files. The
runner checks each patch's declared paths and SHA-256, applies it identically to
each fresh worktree before warmup, and records before/after file hashes and
modes. Setup is excluded from both session and warmup totals. Adding or changing
setup requires a fresh output directory; `--resume` rejects mismatched setup
descriptors or per-cell proofs and cannot reuse an older unpatched sample.

The recorded `tests_started` counter includes nested test-runner output from
retries; it is not a count of unique selected tests. An audit of all four Rust
1.98.0 revision 1 Codex logs confirmed the same 3,439 selected test identities in
every run. Each stock run retried one flaky test, whose nested output increased
the recorded counter to 3,440. Historical counters and timings remain unchanged.

Pass `--project ruff`, `--project uv`, or `--project codex` to run individual
scenarios. Repetitions counterbalance toolchain order across complete replays:
stock followed by Ohm in the first repetition, Ohm followed by stock in the
second. Detailed per-command logs and `results.json` are written beneath the
output directory. Add `--background` on remote hosts to survive an SSH
disconnect; the detached process maintains `run.log` and `status.json` in the
same output directory. Add `--resume` with the identical benchmark options to
preserve completed samples after an interruption. An incomplete sample always
restarts from a fresh worktree, target, shared build, and logs; its previous
artifacts and any interrupted source edits remain recoverable under
`interrupted/<project>/<toolchain>/<repetition>/<attempt>/`. This keeps both
warmup and timed samples comparable after failures. The idle guard recognizes
compiler children in the benchmark's process group even if short-lived native
compiler parents exit between process snapshots.

Fixtures can be inspected with `--dry-run`. The uv integration test requires
Python 3.12, and the Ruff and Codex scenarios require `cargo-nextest`; Codex also
requires `just`. Revision 17's fine-grained locking can exceed the default
1,024-descriptor limit on Codex's 1,029-crate test graph; raise the soft limit
before starting a complete replay.

If your shell sets `PYTHONSAFEPATH=1`, run the trusted repository script with
`env -u PYTHONSAFEPATH python3 scripts/replay_sessions.py ...` so Python can
import its sibling `benchmark.py` module.

`--source-path ruff=/path/to/ruff` supplies Git objects; it does not select the
checkout's current revision or change the recorded commands. A new workload needs a
separate JSON fixture with pinned source revisions, actual edits, commands, and
environment. Keep the existing fixture unchanged when comparing old releases.

## Ruff workflow

[`ruff.json`](ruff.json) records a sequence from
[Ruff PR #27736](https://github.com/astral-sh/ruff/pull/27736): simplifying
recursive attribute inference, indexing its dependencies per class, and
implementing component fixed points. It starts at `21c9b077ab` and applies the
three complete committed edits through `4b00c689c3`. The selected validation
commands come from that development session, rather than modifying the older
fixture and attributing its existing measurements to different work.

Both toolchains use the pinned `AGENTS.md` development profile: opt-level 1,
`CARGO_PROFILE_DEV_LTO=off`, and line-table debug information. Focused runs select
`--test mdtest`; complete affected-package validation remains broad. Snapshot
updates and forced passes are disabled, so a changed expectation fails the
replay. There are eight nextest commands, three Clippy commands, and one format
check. No standalone `cargo check` is invented for this session; its primary
check-and-test metric consists of the eight nextest commands, including their
actual test execution.

Rust 1.98 introduces Clippy's `format_push_string` lint, which fails the pinned
historical Ruff source under `-D warnings` with both stock Rust and Ohm. The
separate [Rust 1.98-compatible fixture](ruff-rust-1.98.json) preserves every
recorded source revision, edit, test, and profile while allowing only that new
lint for both toolchains' three Clippy commands. The canonical
[`ruff.json`](ruff.json) and all historical measurements remain unchanged.

```sh
ulimit -n 65536
python3 scripts/replay_sessions.py \
  --project ruff \
  --scenario scripts/session_replays/ruff-rust-1.98.json \
  --source-path ruff=/path/to/ruff \
  --upstream 1.98.0 \
  --ohm ohm-1.98.0-8 \
  --output-dir /tmp/ohm-ruff-session-benchmarks-r8 \
  --jobs 8 \
  --repetitions 2 \
  --require-idle \
  --background
```

This is the default Ruff replay, alongside `uv.json` and `codex.json`. To
reproduce the older release-comparison workload on Rust 1.98, pass
`--scenario scripts/session_replays/ruff-historical-rust-1.98.json` instead;
this applies the same narrow Clippy compatibility adjustment. The original
`ruff-historical.json` edits, commands, and recorded results remain unchanged.

### Rust 1.98.0 revision 8 measurements

The [complete revision 8 Ruff results](release-1.98.0-8-ruff.json) contain both counterbalanced repetitions and every recorded command, as a subset of the three-project study below. The study finished on September 3, 2026 (UTC), on a Linux host (AMD EPYC 9V74 80-Core Processor, 32 logical CPUs), with eight build jobs. Baseline warmups are excluded. Both compilers use the same test selectors, report matching test counts, and retain only the existing `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-8 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    442.80 s |     276.29 s |   166.52 s |    37.60% |
| All recorded commands        |    442.50 s |     275.98 s |   166.51 s |    37.63% |
| Checks and tests (`nextest`) |    280.39 s |     208.38 s |    72.01 s |    25.68% |
| `cargo clippy`               |    155.61 s |      59.93 s |    95.68 s |    61.48% |
| `cargo fmt`                  |      6.50 s |       7.67 s |    −1.17 s |   −17.95% |

The check-and-test breakdown includes actual test execution and excludes Clippy and formatting. Slower measurements remain included:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-8 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.59 s |       1.63 s |    −0.04 s |    −2.31% |
| Simplification             |     61.60 s |      53.38 s |     8.22 s |    13.34% |
| Dependency indexing        |     97.79 s |      68.60 s |    29.19 s |    29.85% |
| Component fixed points     |    119.41 s |      84.77 s |    34.64 s |    29.01% |

### Rust 1.98.0 revision 7 measurements

The [complete revision 7 Ruff results](release-1.98.0-7-ruff.json) contain both
counterbalanced repetitions and every recorded command, as a subset of the
three-project study below. The study finished on September 3, 2026 (UTC), on an
AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs. Baseline
warmups are excluded. Both compilers use the same test selectors, report matching
test counts, and retain only the existing `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-7 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    442.41 s |     276.47 s |   165.94 s |    37.51% |
| All recorded commands        |    442.11 s |     276.17 s |   165.94 s |    37.53% |
| Checks and tests (`nextest`) |    280.06 s |     207.68 s |    72.38 s |    25.85% |
| `cargo clippy`               |    155.51 s |      60.86 s |    94.65 s |    60.86% |
| `cargo fmt`                  |      6.54 s |       7.63 s |    −1.09 s |   −16.63% |

The check-and-test breakdown includes actual test execution and excludes Clippy
and formatting. Slower measurements remain included:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-7 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.61 s |       1.61 s |     0.00 s |     0.11% |
| Simplification             |     61.44 s |      52.42 s |     9.02 s |    14.69% |
| Dependency indexing        |     97.76 s |      68.86 s |    28.90 s |    29.57% |
| Component fixed points     |    119.25 s |      84.80 s |    34.45 s |    28.89% |

### Rust 1.98.0 revision 6 measurements

The [complete revision 6 Ruff results](release-1.98.0-6-ruff.json) contain both
counterbalanced repetitions and every recorded command, as a subset of the
three-project study below. They were collected on September 2, 2026 (UTC), on an
AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs. Baseline
warmups are excluded. Both compilers use the same test selectors, report matching
test counts, and retain only the existing `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-6 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    420.98 s |     267.50 s |   153.48 s |    36.46% |
| All recorded commands        |    420.67 s |     267.19 s |   153.48 s |    36.49% |
| Checks and tests (`nextest`) |    268.59 s |     204.50 s |    64.08 s |    23.86% |
| `cargo clippy`               |    145.56 s |      55.05 s |    90.51 s |    62.18% |
| `cargo fmt`                  |      6.52 s |       7.63 s |    −1.11 s |   −17.03% |

The check-and-test breakdown includes actual test execution and excludes Clippy
and formatting. Slower measurements remain included:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-6 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.60 s |       1.61 s |    −0.01 s |    −0.81% |
| Simplification             |     59.43 s |      52.89 s |     6.54 s |    11.01% |
| Dependency indexing        |     93.38 s |      66.91 s |    26.46 s |    28.34% |
| Component fixed points     |    114.18 s |      83.09 s |    31.09 s |    27.23% |

### Rust 1.98.0 revision 5 measurements

The [complete revision 5 Ruff results](release-1.98.0-5-ruff.json) contain both
counterbalanced repetitions and every recorded command, as a subset of the
three-project study below. They were collected on August 31, 2026 (UTC), on an
AMD EPYC-Milan Linux host with 32 logical CPUs and eight build jobs. Baseline
warmups are excluded. Both compilers use the same test selectors, report matching
test counts, and retain only the existing `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    528.74 s |     343.08 s |   185.67 s |    35.11% |
| All recorded commands        |    528.06 s |     342.35 s |   185.71 s |    35.17% |
| Checks and tests (`nextest`) |    332.19 s |     253.25 s |    78.94 s |    23.76% |
| `cargo clippy`               |    188.63 s |      80.73 s |   107.90 s |    57.20% |
| `cargo fmt`                  |      7.24 s |       8.37 s |    −1.13 s |   −15.61% |

The check-and-test breakdown includes actual test execution and excludes Clippy
and formatting. Slower measurements remain included:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.96 s |       1.84 s |     0.13 s |     6.42% |
| Simplification             |     75.23 s |      63.25 s |    11.99 s |    15.93% |
| Dependency indexing        |    114.65 s |      86.69 s |    27.97 s |    24.39% |
| Component fixed points     |    140.34 s |     101.48 s |    38.86 s |    27.69% |

### Rust 1.98.0 revision 3 measurements

The [complete revision 3 Ruff results](release-1.98.0-3-ruff.json) contain both
counterbalanced repetitions and every recorded command, as a subset of the
three-project study below. They were collected on August 27, 2026 (UTC), on an
AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs. Baseline
warmups are excluded. Both compilers use the same test selectors, report matching
test counts, and retain only the existing `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-3 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    456.51 s |     289.95 s |   166.56 s |    36.48% |
| All recorded commands        |    456.20 s |     289.65 s |   166.56 s |    36.51% |
| Checks and tests (`nextest`) |    288.38 s |     215.82 s |    72.57 s |    25.16% |
| `cargo clippy`               |    161.20 s |      66.07 s |    95.13 s |    59.01% |
| `cargo fmt`                  |      6.62 s |       7.76 s |    −1.14 s |   −17.19% |

The unchanged focused baseline and the formatting check are slower with Ohm and
remain included. The check-and-test breakdown includes actual test execution
and excludes Clippy and formatting:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-3 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.68 s |       1.73 s |    −0.06 s |    −3.51% |
| Simplification             |     62.76 s |      54.57 s |     8.19 s |    13.04% |
| Dependency indexing        |    100.55 s |      72.48 s |    28.06 s |    27.91% |
| Component fixed points     |    123.40 s |      87.03 s |    36.38 s |    29.48% |

The second Ruff pair straddles the interruption described in the
[complete-study methodology](#rust-1980-revision-3-complete-development-session-results).
Its completed Ohm run was preserved unchanged; the stock run restarted from a
fresh worktree and target after an untimed warmup was rejected.

### Rust 1.98.0 revision 2 measurements

The [complete revision 2 Ruff results](release-1.98.0-2-ruff.json) contain both
counterbalanced repetitions and every recorded command. The study used a quiet
AMD EPYC-Milan host with 32 logical CPUs and eight build jobs. Baseline warmups
are excluded; each pair used identical test selectors and reported matching
test counts, also matching the previous release's recorded counts. Both
toolchains retain the same narrow `format_push_string` Clippy allowance.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-2 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    529.35 s |     347.61 s |   181.74 s |    34.33% |
| All recorded commands        |    528.66 s |     346.90 s |   181.76 s |    34.38% |
| Checks and tests (`nextest`) |    335.19 s |     254.38 s |    80.81 s |    24.11% |
| `cargo clippy`               |    186.30 s |      84.42 s |   101.88 s |    54.69% |
| `cargo fmt`                  |      7.16 s |       8.10 s |    −0.94 s |   −13.09% |

The recorded formatting check is slower with Ohm and remains included. The
check-and-test breakdown includes actual test execution and excludes Clippy
and formatting:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-2 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.96 s |       1.84 s |     0.12 s |     5.90% |
| Simplification             |     75.39 s |      64.73 s |    10.66 s |    14.14% |
| Dependency indexing        |    117.00 s |      86.82 s |    30.17 s |    25.79% |
| Component fixed points     |    140.85 s |     100.99 s |    39.87 s |    28.30% |

### Rust 1.98.0 revision 1 measurements

The [complete Rust 1.98 Ruff results](release-1.98.0-1-ruff.json) contain both
counterbalanced repetitions and every recorded command. Baseline warmups are
excluded; each compared test command ran the same selected tests. Both
toolchains use the same narrow compatibility allowance for the new
`format_push_string` Clippy lint.

| Scope                        | Rust 1.98.0 | Ohm 1.98.0-1 | Time saved | Reduction |
| ---------------------------- | ----------: | -----------: | ---------: | --------: |
| Complete session             |    526.72 s |     353.30 s |   173.43 s |    32.93% |
| All recorded commands        |    526.05 s |     352.61 s |   173.43 s |    32.97% |
| Checks and tests (`nextest`) |    332.53 s |     255.66 s |    76.87 s |    23.12% |
| `cargo clippy`               |    186.31 s |      89.10 s |    97.21 s |    52.18% |
| `cargo fmt`                  |      7.22 s |       7.86 s |    −0.64 s |    −8.92% |

The check-and-test breakdown includes actual test execution and excludes Clippy
and formatting:

| Check/test phase           | Rust 1.98.0 | Ohm 1.98.0-1 | Time saved | Reduction |
| -------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged focused baseline |      1.91 s |       1.81 s |     0.09 s |     4.91% |
| Simplification             |     75.72 s |      66.35 s |     9.37 s |    12.37% |
| Dependency indexing        |    115.21 s |      85.79 s |    29.42 s |    25.54% |
| Component fixed points     |    139.69 s |     101.71 s |    37.98 s |    27.19% |

### Revision 20 measurements

The [complete Ruff results](release-1.97.1-20-ruff.json) contain both counterbalanced repetitions and all recorded commands. Baseline warmups are excluded; each compared test command ran the same selected tests.

| Scope                        | Rust 1.97.1 | Ohm 1.97.1-20 | Time saved | Reduction |
| ---------------------------- | ----------: | ------------: | ---------: | --------: |
| Complete session             |    457.17 s |      268.70 s |   188.48 s |    41.23% |
| All recorded commands        |    456.86 s |      268.39 s |   188.47 s |    41.25% |
| Checks and tests (`nextest`) |    264.80 s |      199.49 s |    65.31 s |    24.66% |
| `cargo clippy`               |    185.62 s |       61.89 s |   123.73 s |    66.66% |
| `cargo fmt`                  |      6.43 s |        7.01 s |    −0.57 s |    −8.91% |

The check-and-test breakdown includes actual test execution and excludes Clippy and formatting:

| Check/test phase           | Rust 1.97.1 | Ohm 1.97.1-20 | Time saved | Reduction |
| -------------------------- | ----------: | ------------: | ---------: | --------: |
| Unchanged focused baseline |      1.60 s |        1.61 s |    −0.00 s |    −0.23% |
| Simplification             |     58.21 s |       49.52 s |     8.69 s |    14.92% |
| Dependency indexing        |     92.10 s |       66.52 s |    25.58 s |    27.77% |
| Component fixed points     |    112.89 s |       81.84 s |    31.05 s |    27.50% |

Revision-19 and revision-18 measurements remain below as immutable historical evidence.

### Revision 19 measurements

The [complete Ruff results](release-1.97.1-19-ruff.json) contain both counterbalanced repetitions and all recorded commands. Baseline warmups are excluded; each compared test command ran the same selected tests.

| Scope                        | Rust 1.97.1 | Ohm 1.97.1-19 | Time saved | Reduction |
| ---------------------------- | ----------: | ------------: | ---------: | --------: |
| Complete session             |    473.59 s |      421.72 s |    51.87 s |    10.95% |
| All recorded commands        |    472.63 s |      421.45 s |    51.18 s |    10.83% |
| Checks and tests (`nextest`) |    271.40 s |      280.70 s |    −9.30 s |    −3.43% |
| `cargo clippy`               |    194.80 s |      133.72 s |    61.08 s |    31.35% |
| `cargo fmt`                  |      6.44 s |        7.03 s |    −0.60 s |    −9.27% |

The check-and-test breakdown includes actual test execution and excludes Clippy and formatting:

| Check/test phase           | Rust 1.97.1 | Ohm 1.97.1-19 | Time saved | Reduction |
| -------------------------- | ----------: | ------------: | ---------: | --------: |
| Unchanged focused baseline |      1.61 s |        1.59 s |     0.02 s |     1.15% |
| Simplification             |     59.67 s |       60.80 s |    −1.13 s |    −1.89% |
| Dependency indexing        |     94.18 s |       98.41 s |    −4.23 s |    −4.49% |
| Component fixed points     |    115.94 s |      119.90 s |    −3.97 s |    −3.42% |

Revision-18 measurements remain below as immutable historical evidence.

### Revision 18 measurements

The [complete Ruff results](release-1.97.1-18-ruff.json) contain both
counterbalanced repetitions and all 12 per-command timings. This study used a
separate, idle Linux devbox with 32 logical CPUs (AMD EPYC 7763) and eight build
jobs. All commands passed, paired test counts matched, and the interference
guard observed no competing compilations. An earlier attempt on the historical
study's host was rejected during warmup when another build began; none of that
attempt is included here.

| Scope                        | Rust 1.97.1 | Ohm 1.97.1-18 | Time saved | Reduction |
| ---------------------------- | ----------: | ------------: | ---------: | --------: |
| Complete session             |    429.44 s |      373.78 s |    55.67 s |    12.96% |
| All recorded commands        |    429.19 s |      373.52 s |    55.67 s |    12.97% |
| Checks and tests (`nextest`) |    247.77 s |      250.72 s |    −2.95 s |    −1.19% |
| `cargo clippy`               |    174.93 s |      115.65 s |    59.28 s |    33.89% |
| `cargo fmt`                  |      6.49 s |        7.16 s |    −0.66 s |   −10.23% |

The primary check-and-test total includes the unchanged focused baseline and
the following three edit-to-test phases. Clippy and formatting are excluded
from this breakdown. Each phase includes the actual selected tests, not just
compiler time.

| Check/test phase           | Rust 1.97.1 | Ohm 1.97.1-18 | Time saved | Reduction |
| -------------------------- | ----------: | ------------: | ---------: | --------: |
| Unchanged focused baseline |      1.58 s |        1.59 s |    −0.02 s |    −1.15% |
| Simplification             |     54.64 s |       54.32 s |     0.31 s |     0.57% |
| Dependency indexing        |     85.50 s |       85.81 s |    −0.31 s |    −0.36% |
| Component fixed points     |    106.06 s |      108.99 s |    −2.94 s |    −2.77% |

The two-run means show a 12.96% whole-session improvement, but not an
edit-to-test improvement: the check-and-test total is 1.19% slower. Baseline
warmups are excluded from all these tables. Because both the source-edit
sequence and the machine differ, these results do not replace a row in the
historical three-project aggregate below. At the time, the main README combined this
new Ruff result with the recorded revision-18 uv and Codex results. Its totals
sum those three paired project means; they are not a new simultaneous run on
one host.

## Rust 1.98.0 revision 8 complete development-session results

The [complete revision 8 results](release-1.98.0-8-baseline.json) compare released Ohm 1.98.0-8 with stock Rust 1.98.0, completing on September 3, 2026 (UTC). All three projects ran sequentially on a Linux host (AMD EPYC 9V74 80-Core Processor, 32 logical CPUs), with eight build jobs and two counterbalanced repetitions per compiler. The launch passed six five-second CPU checks with at least 95% idle, at most 0.5% I/O wait and 0.1% steal time, and no unrelated compiler processes. All 12 accepted replays, 148 timed commands, and 32 excluded warmup commands passed without observed external compilation.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-8 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    442.80 s |     276.29 s |   166.52 s |    37.60% |
| uv session                                 |    150.58 s |     109.66 s |    40.92 s |    27.18% |
| Codex session                              |    535.54 s |     294.60 s |   240.94 s |    44.99% |
| All sessions                               |  1,128.92 s |     680.55 s |   448.38 s |    39.72% |
| `cargo check`                              |    155.60 s |      53.13 s |   102.47 s |    65.85% |
| `cargo test`, `cargo nextest`, `just test` |    617.10 s |     469.02 s |   148.08 s |    24.00% |
| `cargo clippy`                             |    338.82 s |     145.59 s |   193.22 s |    57.03% |
| `cargo fmt`                                |     16.71 s |      12.12 s |     4.60 s |    27.49% |
| All commands                               |  1,128.23 s |     679.86 s |   448.37 s |    39.74% |

Each project row is the mean of two complete sessions, including the recorded source edits and runner overhead but excluding baseline warmups. The aggregate sums those three project means; command-category rows omit source edits and runner overhead. Two repetitions give preliminary estimates, not confidence intervals. Both compilers execute the same pinned sources, edits, commands, and tests. Dependencies were prefetched with locked manifests, but replay commands remain online. The current-session replay used Python 3.12.13, just 1.58.0, cargo-nextest 0.9.140, uv 0.11.20. Each compiler pair used the same helpers. The fixtures invoke Cargo and just directly; helper versions and binary hashes are recorded in the artifacts. The Ohm configuration retains the explicit shared build directory and potentially unsound procedural-macro trust `all`; it does not measure packaged defaults alone. Native-tool trust and the optional lockfile parse cache were not enabled. Cargo status messages are not compiler-invocation counts.

All four Codex runs use the unchanged [`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture, its hash-pinned setup patch, and the same 11 published test exclusions. Independent nextest inventories confirm the same 3,439 unique tests in every final package run. The artifacts retain every observed test-start count and the inventory hash. The six final edited source files match across all four runs. All replays used a short, private temporary directory.

The separate [historical Ruff study](release-1.98.0-8-ruff-historical.json) adds four replays and 48 timed commands and is excluded from the headline aggregate. The standard refresh covers 16 replays, 196 timed commands, and 40 untimed warmup commands. A separate [uv feature ablation](release-1.98.0-8-uv-feature-ablation.json) adds eight replays with 16 timed commands and 16 warmups; it is also excluded from the headline aggregate.

The benchmark runners, source fixtures, setup patch, and test exclusions are unchanged from [the release coordinator](https://github.com/astral-sh/ohm/commit/d172b411f28dc2dd0ddc0c55cd394485b56f570e). The artifacts retain source, fixture, setup, runner, release-archive, toolchain, inventory, and execution-receipt hashes. Both toolchains' versions and executable hashes were recorded before timing. These are fresh comparisons against stock Rust, not a controlled comparison between Ohm releases. All historical results remain unchanged.

## uv feature ablation with Rust 1.98.0 revision 8

The [feature-ablation results](release-1.98.0-8-uv-feature-ablation.json) replay the existing [`uv-feature-ablation.json`](uv-feature-ablation.json) fixture with four Ohm flag combinations. They completed on September 3, 2026 (UTC), on a Linux host (AMD EPYC 9V74 80-Core Processor, 32 logical CPUs). This is an Ohm-only experiment, separate from the stock comparison and headline aggregate. Each cell starts with fresh build artifacts and two untimed warmup commands, then applies the same private parser edit, checks the downstream `uv-client` crate, and runs the directly edited parser tests.

One quiet preflight was rejected before any ablation benchmark command started. The retained recovery passed the unchanged full quiet gate and preserved all 12 earlier current-session replays.

| Public API hashing | Proc-macro cache | Downstream check | Parser tests | Complete session |
| ------------------ | ---------------- | ---------------: | -----------: | ---------------: |
| On                 | On               |           1.74 s |       1.64 s |           3.42 s |
| Off                | On               |           4.14 s |       1.57 s |           5.74 s |
| On                 | Off              |           1.69 s |       1.62 s |           3.35 s |
| Off                | Off              |           4.28 s |       1.63 s |           5.95 s |

Each row averages two repetitions. All eight replays, 16 timed commands, and 16 warmups passed with matching test counts and no observed external compilation. The runner rotates the four configurations between repetitions; the artifact records their exact order and `-Zpublic-api-hash=no` / `-Zcache-proc-macros=no` overrides. Other Ohm defaults, the shared build directory, and explicit procedural-macro trust remain unchanged. This small fixture measures these feature combinations; it does not isolate individual changes in revision 8 or establish an effect across other workloads.

To reproduce it with the same installed tools and private temporary directory:

```sh
python3 scripts/replay_sessions.py \
  --project uv --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv --ohm ohm-1.98.0-8 \
  --feature-matrix --jobs 8 --repetitions 2 --require-idle \
  --output-dir /path/to/new-empty-ablation-results
```

## Rust 1.98.0 revision 7 complete development-session results

The [complete revision 7 results](release-1.98.0-7-baseline.json) compare released
Ohm 1.98.0-7 with stock Rust 1.98.0, completing on September 3, 2026 (UTC).
All three projects ran sequentially on one AMD EPYC 9V74 Linux host with 32 logical CPUs,
eight build jobs, and two counterbalanced repetitions per compiler. The launch passed six
five-second CPU checks with at least 95% idle, at most 0.5% I/O wait and 0.1% steal time,
and no unrelated compiler processes. All 12 accepted replays, 148 timed commands, and 32 excluded
warmup commands passed without observed external compilation.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-7 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    442.41 s |     276.47 s |   165.94 s |    37.51% |
| uv session                                 |    150.42 s |     109.24 s |    41.18 s |    27.38% |
| Codex session                              |    532.66 s |     294.31 s |   238.35 s |    44.75% |
| All sessions                               |  1,125.49 s |     680.02 s |   445.47 s |    39.58% |
| `cargo check`                              |    154.42 s |      52.29 s |   102.13 s |    66.14% |
| `cargo test`, `cargo nextest`, `just test` |    615.95 s |     469.97 s |   145.98 s |    23.70% |
| `cargo clippy`                             |    337.66 s |     145.02 s |   192.64 s |    57.05% |
| `cargo fmt`                                |     16.79 s |      12.06 s |     4.72 s |    28.13% |
| All commands                               |  1,124.81 s |     679.35 s |   445.47 s |    39.60% |

Each project row is the mean of two complete sessions, including the recorded source edits
and runner overhead but excluding baseline warmups. The aggregate sums those three project
means; command-category rows omit source edits and runner overhead. Two repetitions give
preliminary estimates, not confidence intervals. Both compilers execute the same pinned
sources, edits, commands, and tests. Dependencies were prefetched with locked manifests,
but replay commands remain online. The replay used Python 3.12.13, just 1.58.0, and
cargo-nextest 0.9.140. Both hosts retained uv 0.11.20; each compiler pair used the same helpers. The fixtures
invoke Cargo and just directly. Helper versions and binary hashes are recorded in the artifacts. The Ohm configuration retains the explicit shared build directory
and potentially unsound procedural-macro trust `all`; it does not measure packaged defaults
alone. Native-tool trust and the optional lockfile parse cache were not enabled. Cargo
status messages are not compiler-invocation counts.

All four Codex runs use the unchanged
[`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture,
its hash-pinned setup patch, and the same 11 published test exclusions. Independent nextest
inventories confirm the same 3,439 unique tests in every final package run. The artifacts
retain every observed test-start count and the inventory hash. The six final edited source
files match across all four runs. All replays used a short, private temporary directory.

The separate [historical Ruff study](release-1.98.0-7-ruff-historical.json) adds four
replays and 48 timed commands and is excluded from the headline aggregate. The standard
refresh covers 16 replays, 196 timed commands, and 40 untimed warmup commands. A separate
[uv feature ablation](release-1.98.0-7-uv-feature-ablation.json) adds eight replays with
16 timed commands and 16 warmups; it is also excluded from the headline aggregate.

The benchmark runners, source fixtures, setup patch, and test exclusions are unchanged from
[the release coordinator](https://github.com/astral-sh/ohm/commit/d172b411f28dc2dd0ddc0c55cd394485b56f570e).
The artifacts retain source, fixture, setup, runner, release-archive, toolchain, inventory,
and execution-receipt hashes. Both hosts used the identical GitHub release assets after their public
mirror downloads timed out; both verified SHA-256 hashes before timing.

These are fresh stock
comparisons, not a controlled revision-6-versus-revision-7 experiment. All historical results
remain unchanged.

## uv feature ablation with Rust 1.98.0 revision 7

The [feature-ablation results](release-1.98.0-7-uv-feature-ablation.json) replay the
existing [`uv-feature-ablation.json`](uv-feature-ablation.json) fixture with four Ohm flag
combinations. They completed on September 3, 2026 (UTC), on the current-session
host after the three-project suite. This is an Ohm-only experiment, separate from the stock
comparison and headline aggregate. Each cell starts with fresh build artifacts and two
untimed warmup commands, then applies the same private parser edit, checks the downstream
`uv-client` crate, and runs the directly edited parser tests.

| Public API hashing | Proc-macro cache | Downstream check | Parser tests | Complete session |
| ------------------ | ---------------- | ---------------: | -----------: | ---------------: |
| On                 | On               |           1.64 s |       1.59 s |           3.26 s |
| Off                | On               |           3.86 s |       1.61 s |           5.50 s |
| On                 | Off              |           1.76 s |       1.66 s |           3.46 s |
| Off                | Off              |           3.95 s |       1.67 s |           5.65 s |

Each row averages two repetitions. All eight replays, 16 timed commands, and 16 warmups
passed with matching test counts and no observed external compilation. The runner rotates
the four configurations between repetitions; the artifact records their exact order and
`-Zpublic-api-hash=no` / `-Zcache-proc-macros=no` overrides. Other Ohm defaults, the shared
build directory, and explicit procedural-macro trust remain unchanged. This small fixture
measures these feature combinations; it does not isolate individual changes in revision 7
or establish an effect across other workloads.

To reproduce it with the same installed tools and private temporary directory:

```sh
python3 scripts/replay_sessions.py \
  --project uv --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv --ohm ohm-1.98.0-7 \
  --feature-matrix --jobs 8 --repetitions 2 --require-idle \
  --output-dir /path/to/new-empty-ablation-results
```

## Rust 1.98.0 revision 6 complete development-session results

The [complete revision 6 results](release-1.98.0-6-baseline.json) compare released
Ohm 1.98.0-6 with stock Rust 1.98.0, completing on September 2, 2026 (UTC).
All three projects ran sequentially on one AMD EPYC 9V74 Linux host with 32 logical CPUs,
eight build jobs, and two counterbalanced repetitions per compiler. The launch passed six
five-second CPU checks with at least 95% idle, at most 0.5% I/O wait and 0.1% steal time,
and no unrelated compiler processes. All 12 accepted replays, 148 timed commands, and 32 excluded
warmup commands passed without observed external compilation.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-6 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    420.98 s |     267.50 s |   153.48 s |    36.46% |
| uv session                                 |    147.01 s |     107.73 s |    39.28 s |    26.72% |
| Codex session                              |    518.11 s |     284.51 s |   233.60 s |    45.09% |
| All sessions                               |  1,086.10 s |     659.74 s |   426.36 s |    39.26% |
| `cargo check`                              |    148.40 s |      49.77 s |    98.63 s |    66.46% |
| `cargo test`, `cargo nextest`, `just test` |    598.60 s |     460.86 s |   137.74 s |    23.01% |
| `cargo clippy`                             |    321.72 s |     136.34 s |   185.38 s |    57.62% |
| `cargo fmt`                                |     16.69 s |      12.07 s |     4.61 s |    27.66% |
| All commands                               |  1,085.40 s |     659.04 s |   426.36 s |    39.28% |

Each project row is the mean of two complete sessions, including the recorded source edits
and runner overhead but excluding baseline warmups. The aggregate sums those three project
means; command-category rows omit source edits and runner overhead. Two repetitions give
preliminary estimates, not confidence intervals. Both compilers execute the same pinned
sources, edits, commands, and tests. Dependencies were prefetched with locked manifests,
but replay commands remain online. The replay used Python 3.12.13, just 1.58.0, and
cargo-nextest 0.9.140. Both hosts retained uv 0.11.20; each compiler pair used the same helpers. The fixtures
invoke Cargo and just directly. Helper versions and binary hashes are recorded in the artifacts. The Ohm configuration retains the explicit shared build directory
and potentially unsound procedural-macro trust `all`; it does not measure packaged defaults
alone. Native-tool trust and the optional lockfile parse cache were not enabled. Cargo
status messages are not compiler-invocation counts.

All four Codex runs use the unchanged
[`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture,
its hash-pinned setup patch, and the same 11 published test exclusions. Independent nextest
inventories confirm the same 3,439 unique tests in every final package run. The artifacts
retain every observed test-start count and the inventory hash. The six final edited source
files match across all four runs. All replays used a short, private temporary directory.

The separate [historical Ruff study](release-1.98.0-6-ruff-historical.json) adds four
replays and 48 timed commands and is excluded from the headline aggregate. The standard
refresh covers 16 replays, 196 timed commands, and 40 untimed warmup commands. A separate
[uv feature ablation](release-1.98.0-6-uv-feature-ablation.json) adds eight replays with
16 timed commands and 16 warmups; it is also excluded from the headline aggregate.

The benchmark runners, source fixtures, setup patch, and test exclusions are unchanged from
[the release coordinator](https://github.com/astral-sh/ohm/commit/d172b411f28dc2dd0ddc0c55cd394485b56f570e).
The artifacts retain source, fixture, setup, runner, release-archive, toolchain, inventory,
and execution-receipt hashes. Both hosts used the identical GitHub release assets after their public
mirror downloads timed out; both verified SHA-256 hashes before timing.

These are fresh stock
comparisons, not a controlled revision-5-versus-revision-6 experiment. All historical results
remain unchanged.

## uv feature ablation with Rust 1.98.0 revision 6

The [feature-ablation results](release-1.98.0-6-uv-feature-ablation.json) replay the
existing [`uv-feature-ablation.json`](uv-feature-ablation.json) fixture with four Ohm flag
combinations. They completed on September 2, 2026 (UTC), on the current-session
host after the three-project suite. This is an Ohm-only experiment, separate from the stock
comparison and headline aggregate. Each cell starts with fresh build artifacts and two
untimed warmup commands, then applies the same private parser edit, checks the downstream
`uv-client` crate, and runs the directly edited parser tests.

| Public API hashing | Proc-macro cache | Downstream check | Parser tests | Complete session |
| ------------------ | ---------------- | ---------------: | -----------: | ---------------: |
| On                 | On               |           1.41 s |       1.49 s |           2.94 s |
| Off                | On               |           3.33 s |       1.46 s |           4.82 s |
| On                 | Off              |           1.44 s |       1.55 s |           3.05 s |
| Off                | Off              |           3.59 s |       1.54 s |           5.17 s |

Each row averages two repetitions. All eight replays, 16 timed commands, and 16 warmups
passed with matching test counts and no observed external compilation. The runner rotates
the four configurations between repetitions; the artifact records their exact order and
`-Zpublic-api-hash=no` / `-Zcache-proc-macros=no` overrides. Other Ohm defaults, the shared
build directory, and explicit procedural-macro trust remain unchanged. This small fixture
measures these feature combinations; it does not isolate individual changes in revision 6
or establish an effect across other workloads.

To reproduce it with the same installed tools and private temporary directory:

```sh
python3 scripts/replay_sessions.py \
  --project uv --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv --ohm ohm-1.98.0-6 \
  --feature-matrix --jobs 8 --repetitions 2 --require-idle \
  --output-dir /path/to/new-empty-ablation-results
```

## Rust 1.98.0 revision 5 complete development-session results

The [complete revision 5 results](release-1.98.0-5-baseline.json) compare released
Ohm 1.98.0-5 with stock Rust 1.98.0, completing on August 31, 2026 (UTC).
All three projects ran sequentially on one AMD EPYC-Milan Linux host with 32 logical CPUs,
eight build jobs, and two counterbalanced repetitions per compiler. The launch passed six
five-second CPU checks with at least 95% idle, at most 0.5% I/O wait and 0.1% steal time,
and no unrelated compiler processes. All 12 accepted replays, 148 timed commands, and 32 excluded
warmup commands passed without observed external compilation.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    528.74 s |     343.08 s |   185.67 s |    35.11% |
| uv session                                 |    190.85 s |     145.76 s |    45.09 s |    23.63% |
| Codex session                              |    693.53 s |     403.14 s |   290.39 s |    41.87% |
| All sessions                               |  1,413.12 s |     891.97 s |   521.15 s |    36.88% |
| `cargo check`                              |    193.47 s |      70.80 s |   122.67 s |    63.41% |
| `cargo test`, `cargo nextest`, `just test` |    785.24 s |     613.34 s |   171.89 s |    21.89% |
| `cargo clippy`                             |    413.95 s |     192.16 s |   221.78 s |    53.58% |
| `cargo fmt`                                |     18.56 s |      13.33 s |     5.22 s |    28.16% |
| All commands                               |  1,411.21 s |     889.64 s |   521.58 s |    36.96% |

Each project row is the mean of two complete sessions, including the recorded source edits
and runner overhead but excluding baseline warmups. The aggregate sums those three project
means; command-category rows omit source edits and runner overhead. Two repetitions give
preliminary estimates, not confidence intervals. Both compilers execute the same pinned
sources, edits, commands, and tests. Dependencies were prefetched with locked manifests,
but replay commands remain online. The replay used Python 3.12.13, just 1.58.0, and
cargo-nextest 0.9.140. The session host retained uv 0.11.33, while the direct and historical
workflow host retained uv 0.11.20; each compiler pair used the same helpers. The fixtures
invoke Cargo and just directly. Helper versions and binary hashes are recorded in the artifacts. The Ohm configuration retains the explicit shared build directory
and potentially unsound procedural-macro trust `all`; it does not measure packaged defaults
alone. Native-tool trust and the optional lockfile parse cache were not enabled. Cargo
status messages are not compiler-invocation counts.

All four Codex runs use the unchanged
[`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture,
its hash-pinned setup patch, and the same 11 published test exclusions. Independent nextest
inventories confirm the same 3,439 unique tests in every final package run. The artifacts
retain every observed test-start count and the inventory hash. The six final edited source
files match across all four runs. All replays used a short, private temporary directory.

The separate [historical Ruff study](release-1.98.0-5-ruff-historical.json) adds four
replays and 48 timed commands and is excluded from the headline aggregate. The standard
refresh covers 16 replays, 196 timed commands, and 40 untimed warmup commands. A separate
[uv feature ablation](release-1.98.0-5-uv-feature-ablation.json) adds eight replays with
16 timed commands and 16 warmups; it is also excluded from the headline aggregate.

The benchmark runners, source fixtures, setup patch, and test exclusions are unchanged from
[the release coordinator](https://github.com/astral-sh/ohm/commit/d172b411f28dc2dd0ddc0c55cd394485b56f570e).
The artifacts retain source, fixture, setup, runner, release-archive, toolchain, inventory,
and execution-receipt hashes. Before timing, the direct-workflow host downloaded the public
release assets. The session host used the identical GitHub release assets after its public
mirror download timed out; both hosts verified SHA-256 hashes.

These are fresh stock
comparisons, not a controlled revision-3-versus-revision-5 experiment. All historical results
remain unchanged.

## uv feature ablation with Rust 1.98.0 revision 5

The [feature-ablation results](release-1.98.0-5-uv-feature-ablation.json) replay the
existing [`uv-feature-ablation.json`](uv-feature-ablation.json) fixture with four Ohm flag
combinations. They completed on August 31, 2026 (UTC), on the current-session
host after the three-project suite. This is an Ohm-only experiment, separate from the stock
comparison and headline aggregate. Each cell starts with fresh build artifacts and two
untimed warmup commands, then applies the same private parser edit, checks the downstream
`uv-client` crate, and runs the directly edited parser tests.

| Public API hashing | Proc-macro cache | Downstream check | Parser tests | Complete session |
| ------------------ | ---------------- | ---------------: | -----------: | ---------------: |
| On                 | On               |           1.76 s |       1.85 s |           3.71 s |
| Off                | On               |           4.14 s |       1.82 s |           6.06 s |
| On                 | Off              |           1.56 s |       1.91 s |           3.56 s |
| Off                | Off              |           4.29 s |       1.91 s |           6.30 s |

Each row averages two repetitions. All eight replays, 16 timed commands, and 16 warmups
passed with matching test counts and no observed external compilation. The runner rotates
the four configurations between repetitions; the artifact records their exact order and
`-Zpublic-api-hash=no` / `-Zcache-proc-macros=no` overrides. Other Ohm defaults, the shared
build directory, and explicit procedural-macro trust remain unchanged. This small fixture
measures these feature combinations; it does not isolate individual changes in revision 5
or establish an effect across other workloads.

The first ablation preflight was rejected before any benchmark command ran: its
sixth five-second interval had 94.38% CPU idle, below the unchanged
95% requirement. No compiler processes were observed, and I/O wait and steal
time met their limits. No ablation warmup or timed command had started. The unchanged
controller then launched only the unstarted ablation after a fresh six-interval quiet
check passed, without `--resume`. No timed work was interrupted or rerun. The
12 completed current replays remained byte for byte unchanged. The rejected log,
quiet samples, failed status, recovery wrapper, and successful recovery proof are
retained in the evidence archive; the ablation artifact records their hashes.

To reproduce it with the same installed tools and private temporary directory:

```sh
python3 scripts/replay_sessions.py \
  --project uv --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv --ohm ohm-1.98.0-5 \
  --feature-matrix --jobs 8 --repetitions 2 --require-idle \
  --output-dir /path/to/new-empty-ablation-results
```

## Rust 1.98.0 revision 3 complete development-session results

The [complete revision 3 results](release-1.98.0-3-baseline.json) compare released
Ohm 1.98.0-3 with stock Rust 1.98.0 on August 27, 2026 (UTC). All three projects
ran sequentially on one AMD EPYC 9V74 Linux host with 32 logical CPUs, eight build
jobs, and two counterbalanced repetitions per compiler. Each launch passed six
five-second CPU checks with at least 95% idle, at most 0.5% I/O wait and 0.1%
steal time, and no unrelated compiler processes. The 12 accepted replays contain
148 timed commands and 32 excluded warmup commands. All accepted commands passed
without observed external compilation.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-3 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    456.51 s |     289.95 s |   166.56 s |    36.48% |
| uv session                                 |    156.05 s |     114.32 s |    41.73 s |    26.74% |
| Codex session                              |    567.06 s |     309.45 s |   257.61 s |    45.43% |
| All sessions                               |  1,179.62 s |     713.73 s |   465.90 s |    39.50% |
| `cargo check`                              |    162.57 s |      56.38 s |   106.18 s |    65.32% |
| `cargo test`, `cargo nextest`, `just test` |    640.97 s |     485.00 s |   155.97 s |    24.33% |
| `cargo clippy`                             |    358.35 s |     159.44 s |   198.91 s |    55.51% |
| `cargo fmt`                                |     17.05 s |      12.21 s |     4.84 s |    28.38% |
| All commands                               |  1,178.94 s |     713.04 s |   465.90 s |    39.52% |

Each project row is the mean of two complete sessions, including the recorded
source edits and runner overhead but excluding baseline warmups. The aggregate
sums those three project means; command-category rows omit source edits and
runner overhead. Both compilers execute the same pinned sources, edits, commands,
and tests. Dependencies were prefetched with locked manifests, but replay commands
remain online. The replay used Python 3.12, just 1.58.0, and cargo-nextest 0.9.140.
The Ohm configuration retains the explicit shared build directory
and potentially unsound procedural-macro trust `all`; it does not measure
packaged defaults alone. Native-tool trust and the optional lockfile parse cache
were not enabled. Cargo status messages are not compiler-invocation counts.

All four Codex runs use the unchanged
[`codex-stable-goal-accounting.json`](codex-stable-goal-accounting.json) fixture,
its hash-pinned setup patch, and the same 11 published test exclusions. Independent
nextest inventories confirm the same 3,439 unique tests in every final package
run. All four logs report 3,439 test starts and no retry markers or flaky-test
summaries. The six final edited source files match across all four runs.

Two interruptions are retained in the evidence and disclosed in the artifacts:

- The initial attempt used a long temporary-directory path. Two unchanged stock
  Codex tests failed because of temporary-path length or its encoded representation.
  Both passed an untimed check after only `TMPDIR` changed. The entire attempt,
  including four completed Ruff/uv runs, was excluded. All 12 accepted runs use
  fresh worktrees and build directories with the short, private `TMPDIR` above.
- During that fresh attempt, the unchanged interference guard rejected the second
  stock Ruff warmup after reporting a `rustc` process whose ownership could not
  be established. Seven completed runs and their 103 command logs were preserved
  byte for byte. The incomplete Ruff run restarted from fresh artifacts through
  the existing `--resume` path, followed by the four unstarted runs. The rejected
  warmup is excluded. The second Ruff pair spans the interruption; the linked
  execution receipts verify unchanged fixtures, sources, tools, environments,
  warmups, guard, and host boot. No additional test was excluded.

The separate [historical Ruff study](release-1.98.0-3-ruff-historical.json) adds
four replays and 48 timed commands, and is not part of the headline aggregate.
The complete refresh therefore covers 16 replays, 196 timed commands, and 40
untimed warmup commands. The artifacts retain source, fixture, setup, runner,
release-archive, toolchain, inventory, and launch hashes. These are fresh stock
comparisons, not a matched revision-2-versus-revision-3 experiment; the earlier
measurements used different hardware. All historical results remain unchanged.

## Rust 1.98.0 revision 2 complete development-session results

The [complete revision 2 results](release-1.98.0-2-baseline.json) compare released
Ohm 1.98.0-2 with stock Rust 1.98.0 using eight build jobs and two counterbalanced
repetitions per toolchain. Ruff and Codex ran sequentially on the same quiet
32-logical-CPU AMD EPYC-Milan host (`linux-1`); uv used a separate quiet
16-logical-CPU AMD EPYC-Milan host (`linux-2`). Warmups and test-only setup are
excluded, while timed commands include actual test execution. The aggregate sums
the three project means; it is not a simultaneous run on one host.

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-2 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    529.35 s |     347.61 s |   181.74 s |    34.33% |
| uv session                                 |    181.84 s |     135.53 s |    46.31 s |    25.47% |
| Codex session                              |    685.38 s |     398.66 s |   286.72 s |    41.83% |
| All sessions                               |  1,396.57 s |     881.79 s |   514.77 s |    36.86% |
| `cargo check`                              |    180.76 s |      70.45 s |   110.32 s |    61.03% |
| `cargo test`, `cargo nextest`, `just test` |    785.69 s |     598.13 s |   187.55 s |    23.87% |
| `cargo clippy`                             |    409.93 s |     198.73 s |   211.19 s |    51.52% |
| `cargo fmt`                                |     18.47 s |      12.75 s |     5.72 s |    30.96% |
| All commands                               |  1,394.85 s |     880.07 s |   514.78 s |    36.91% |

All four Codex replays are fresh runs of the
[elapsed-time-bounded fixture](codex-stable-goal-accounting.json), with the same
11 previously published test exclusions. Each final TUI command passed the same
3,439 selected test identities, with 16 skipped and no retries. No earlier failed
or successful Codex samples were reused. The sanitized metadata records the
per-study runner and fixture hashes, untimed setup proofs, and test-inventory
verification; original counters and timings remain intact.

The slower Ruff formatting check remains included. The
[separate historical Ruff study](release-1.98.0-2-ruff-historical.json) is not part
of this three-project aggregate. Host assignments and the Codex setup differ
from the previous study, so these results are not a controlled revision-1 versus
revision-2 comparison. Earlier published results remain below unchanged.

## Rust 1.98.0 revision 1 complete development-session results

Each project uses its recorded development-session fixture on a separate quiet
Linux host. Both toolchains execute the same commands, edits, and tests; the
measurements include the complete recorded session rather than only selected
compiler work. The sanitized per-command results are recorded in
[`release-1.98.0-1-baseline.json`](release-1.98.0-1-baseline.json).

| Scope                                      | Rust 1.98.0 | Ohm 1.98.0-1 | Time saved | Reduction |
| ------------------------------------------ | ----------: | -----------: | ---------: | --------: |
| Ruff session                               |    526.72 s |     353.30 s |   173.43 s |    32.93% |
| uv session                                 |    142.40 s |     108.55 s |    33.85 s |    23.77% |
| Codex session                              |    497.53 s |     288.97 s |   208.55 s |    41.92% |
| All sessions                               |  1,166.65 s |     750.82 s |   415.83 s |    35.64% |
| `cargo check`                              |    142.73 s |      50.84 s |    91.89 s |    64.38% |
| `cargo test`, `cargo nextest`, `just test` |    650.80 s |     509.87 s |   140.94 s |    21.66% |
| `cargo clippy`                             |    354.66 s |     177.00 s |   177.66 s |    50.09% |
| `cargo fmt`                                |     17.39 s |      12.05 s |     5.35 s |    30.73% |
| All commands                               |  1,165.59 s |     749.75 s |   415.84 s |    35.68% |

The final Codex package test uses the same 11 documented host-sensitive or
flaky-test exclusions for both toolchains as the previous baselines. Its two
repetitions started 3,440, 3,440 stock tests and 3,439, 3,439 Ohm tests; actual
differences are retained rather than presented as exact test-count parity. The
results include canonical and effective scenario hashes, the complete exclusion
expression, the Ruff Clippy compatibility allowance, and every observed test
count.

## Revision 20 complete development-session results

Each project uses its current, recorded development-session fixture. Both toolchains execute the same commands, edits, and tests; the measurements include the complete recorded session rather than only selected compiler work. The sanitized per-command results are recorded in [`release-1.97.1-20-baseline.json`](release-1.97.1-20-baseline.json).

| Scope                                      | Rust 1.97.1 | Ohm 1.97.1-20 | Time saved | Reduction |
| ------------------------------------------ | ----------: | ------------: | ---------: | --------: |
| Ruff session                               |    457.17 s |      268.70 s |   188.48 s |    41.23% |
| uv session                                 |    146.69 s |      107.22 s |    39.47 s |    26.91% |
| Codex session                              |    520.19 s |      276.94 s |   243.25 s |    46.76% |
| All sessions                               |  1,124.05 s |      652.85 s |   471.20 s |    41.92% |
| `cargo check`                              |    139.76 s |       49.66 s |    90.10 s |    64.47% |
| `cargo test`, `cargo nextest`, `just test` |    576.16 s |      444.98 s |   131.18 s |    22.77% |
| `cargo clippy`                             |    390.90 s |      146.45 s |   244.45 s |    62.54% |
| `cargo fmt`                                |     16.50 s |       11.04 s |     5.46 s |    33.08% |
| All commands                               |  1,123.31 s |      652.13 s |   471.18 s |    41.95% |

The final Codex package test uses the same 11 documented host-sensitive or flaky-test exclusions for both toolchains as the revision-18 baseline. Its two repetitions started 3,441, 3,441 stock tests and 3,439, 3,440 Ohm tests; actual differences are retained rather than presented as exact test-count parity. The results include both canonical and effective scenario hashes, the complete exclusion expression, and every observed test count.

## Revision 19 complete development-session results

Each project uses its current, recorded development-session fixture. Both toolchains execute the same commands, edits, and tests; the measurements include the complete recorded session rather than only selected compiler work. The sanitized per-command results are recorded in [`release-1.97.1-19-baseline.json`](release-1.97.1-19-baseline.json).

| Scope                                      | Rust 1.97.1 | Ohm 1.97.1-19 | Time saved | Reduction |
| ------------------------------------------ | ----------: | ------------: | ---------: | --------: |
| Ruff session                               |    473.59 s |      421.72 s |    51.87 s |    10.95% |
| uv session                                 |    151.07 s |      135.45 s |    15.62 s |    10.34% |
| Codex session                              |    550.39 s |      462.98 s |    87.40 s |    15.88% |
| All sessions                               |  1,175.05 s |    1,020.15 s |   154.90 s |    13.18% |
| `cargo check`                              |    150.82 s |      115.73 s |    35.09 s |    23.27% |
| `cargo test`, `cargo nextest`, `just test` |    594.57 s |      597.99 s |    −3.42 s |    −0.58% |
| `cargo clippy`                             |    411.85 s |      294.75 s |   117.11 s |    28.43% |
| `cargo fmt`                                |     16.51 s |       11.08 s |     5.43 s |    32.89% |
| All commands                               |  1,173.75 s |    1,019.55 s |   154.20 s |    13.14% |

The final Codex package test uses the same 11 documented host-sensitive or flaky-test exclusions for both toolchains as the revision-18 baseline. Its two repetitions started 3,439, 3,439 stock tests and 3,439, 3,439 Ohm tests; actual differences are retained rather than presented as exact test-count parity. The results include both canonical and effective scenario hashes, the complete exclusion expression, and every observed test count.

## Compiler-work attribution

Cargo can print `Checking package` before early cutoff discovers that rustc does
not need to run. These progress messages are not compiler invocations. The
results therefore name them `cargo_reported_crates`, and leave
`actual_compiler_invocations` unknown by default instead of treating either
`Checking` or `Compiling` output as proof of executed compiler work.

For a separate attribution run, add:

```sh
--compiler-accounting verbose
```

This sets `CARGO_TERM_VERBOSE=true` equally for both toolchains. The runner
parses Cargo's actual `Running` commands, counts `rustc` and `clippy-driver`
executions, records their crate names, and identifies
`cargo_status_without_compiler_invocation`. A status-only crate can indicate
early cutoff; it can also reflect a build-script-only action, so inspect the
per-command log when assigning a cause. Verbose output has its own overhead:
compare verbose samples only against equally verbose samples, and keep the
default nonverbose mode for headline session timings.

## Historical Ruff workflow with Rust 1.98.0 revision 8

The separate [revision 8 historical Ruff replay](release-1.98.0-8-ruff-historical.json) reruns the unchanged Rust 1.98-compatible historical fixture, including its check-to-test-to-check transitions. It completed on September 3, 2026 (UTC), on a Linux host (AMD EPYC 9V74 80-Core Processor, 32 logical CPUs), with eight build jobs. Both compilers use the same sources, commands, test selections, and narrow Clippy allowance, with two counterbalanced repetitions. All 48 timed commands and eight untimed warmups in the accepted replays passed, with matching test counts and no observed external compilation.

2 quiet preflights were rejected before any historical benchmark command started. The retained recovery passed the unchanged full quiet gate and preserved all 216 earlier direct measurements.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-8 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    403.72 s |     284.56 s |   119.17 s |    29.52% |
| `cargo check`    |     32.07 s |      15.17 s |    16.90 s |    52.70% |
| `cargo nextest`  |    308.21 s |     238.45 s |    69.76 s |    22.63% |
| `cargo clippy`   |     56.65 s |      22.71 s |    33.93 s |    59.90% |
| `cargo fmt`      |      6.53 s |       7.95 s |    −1.42 s |   −21.74% |

These are measured commands from complete historical sessions, not separate microbenchmarks. All commands remain included, including any slower cases. The historical workload is not part of the three-project headline, and its whole-session gain cannot be attributed solely to check reuse.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-8 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.28 s |       0.52 s |    −0.24 s |   −83.73% |
| Workspace dependency and root edit |     16.54 s |       7.58 s |     8.96 s |    54.18% |
| Workspace root-only edit           |     15.24 s |       7.06 s |     8.18 s |    53.65% |

## Historical Ruff workflow with Rust 1.98.0 revision 7

The separate [revision 7 historical Ruff replay](release-1.98.0-7-ruff-historical.json)
reruns the unchanged Rust 1.98-compatible historical fixture, including its
check-to-test-to-check transitions. It completed on September 3, 2026 (UTC),
on an AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs, after that
host finished the direct workflow suite. Both compilers use the same sources, commands,
test selections, and narrow Clippy allowance, with two counterbalanced repetitions. All
48 timed commands and eight untimed warmups in the accepted replays passed, with matching test counts and no
observed external compilation.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-7 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    395.82 s |     274.06 s |   121.76 s |    30.76% |
| `cargo check`    |     31.57 s |      14.46 s |    17.11 s |    54.19% |
| `cargo nextest`  |    301.46 s |     230.17 s |    71.29 s |    23.65% |
| `cargo clippy`   |     56.12 s |      21.58 s |    34.53 s |    61.54% |
| `cargo fmt`      |      6.41 s |       7.58 s |    −1.17 s |   −18.24% |

One incomplete stock Ruff replay was rejected when an unrelated Cargo process overlapped its final timed command. The runner preserved the rejected logs, worktree, and build state, then repeated the entire replay from fresh state after a new quiet check. One recovery quiet preflight was rejected before timing began. All four accepted replays retain the same fixtures, test selections, and interference guards; the 216 completed direct measurements were unchanged.

These are measured commands from complete historical sessions, not separate microbenchmarks.
All commands remain included, including any slower cases. The historical workload is not part
of the three-project headline, and its whole-session gain cannot be attributed solely to
check reuse.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-7 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.28 s |       0.53 s |    −0.25 s |   −88.36% |
| Workspace dependency and root edit |     16.32 s |       7.29 s |     9.03 s |    55.31% |
| Workspace root-only edit           |     14.97 s |       6.64 s |     8.33 s |    55.64% |

## Historical Ruff workflow with Rust 1.98.0 revision 6

The separate [revision 6 historical Ruff replay](release-1.98.0-6-ruff-historical.json)
reruns the unchanged Rust 1.98-compatible historical fixture, including its
check-to-test-to-check transitions. It completed on September 2, 2026 (UTC),
on an AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs, after that
host finished the direct workflow suite. Both compilers use the same sources, commands,
test selections, and narrow Clippy allowance, with two counterbalanced repetitions. All
48 timed commands and eight untimed warmups passed, with matching test counts and no
observed external compilation.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-6 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    395.89 s |     274.65 s |   121.24 s |    30.62% |
| `cargo check`    |     32.46 s |      14.36 s |    18.10 s |    55.76% |
| `cargo nextest`  |    300.49 s |     231.37 s |    69.13 s |    23.00% |
| `cargo clippy`   |     56.27 s |      21.14 s |    35.13 s |    62.43% |
| `cargo fmt`      |      6.39 s |       7.50 s |    −1.11 s |   −17.45% |

These are measured commands from complete historical sessions, not separate microbenchmarks.
All commands remain included, including any slower cases. The historical workload is not part
of the three-project headline, and its whole-session gain cannot be attributed solely to
check reuse.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-6 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.30 s |       0.52 s |    −0.21 s |   −70.43% |
| Workspace dependency and root edit |     17.07 s |       7.23 s |     9.83 s |    57.61% |
| Workspace root-only edit           |     15.09 s |       6.61 s |     8.48 s |    56.19% |

## Historical Ruff workflow with Rust 1.98.0 revision 5

The separate [revision 5 historical Ruff replay](release-1.98.0-5-ruff-historical.json)
reruns the unchanged Rust 1.98-compatible historical fixture, including its
check-to-test-to-check transitions. It completed on August 31, 2026 (UTC),
on an AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs, after that
host finished the direct workflow suite. Both compilers use the same sources, commands,
test selections, and narrow Clippy allowance, with two counterbalanced repetitions. All
48 timed commands and eight untimed warmups passed, with matching test counts and no
observed external compilation.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    397.52 s |     277.72 s |   119.80 s |    30.14% |
| `cargo check`    |     32.04 s |      14.81 s |    17.24 s |    53.79% |
| `cargo nextest`  |    302.92 s |     233.42 s |    69.50 s |    22.94% |
| `cargo clippy`   |     55.88 s |      21.62 s |    34.26 s |    61.30% |
| `cargo fmt`      |      6.40 s |       7.59 s |    −1.19 s |   −18.59% |

These are measured commands from complete historical sessions, not separate microbenchmarks.
All commands remain included, including any slower cases. The historical workload is not part
of the three-project headline, and its whole-session gain cannot be attributed solely to
check reuse.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-5 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.29 s |       0.46 s |    −0.17 s |   −60.83% |
| Workspace dependency and root edit |     16.57 s |       7.49 s |     9.08 s |    54.82% |
| Workspace root-only edit           |     15.19 s |       6.86 s |     8.33 s |    54.82% |

## Historical Ruff workflow with Rust 1.98.0 revision 3

The separate [revision 3 historical Ruff replay](release-1.98.0-3-ruff-historical.json)
reruns the unchanged Rust 1.98-compatible historical fixture, including its
check-to-test-to-check transitions. It completed on August 27, 2026 (UTC), on a
second AMD EPYC 9V74 Linux host with 32 logical CPUs and eight build jobs. This
host is distinct from the current three-project replay host. Both compilers use
the same sources, commands, test selections, and narrow Clippy allowance, with
two counterbalanced repetitions. All 48 timed commands and eight untimed warmups
passed, with matching test counts and no observed external compilation.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-3 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    395.56 s |     279.28 s |   116.28 s |    29.40% |
| `cargo check`    |     31.61 s |      14.56 s |    17.05 s |    53.92% |
| `cargo nextest`  |    301.05 s |     234.11 s |    66.94 s |    22.23% |
| `cargo clippy`   |     56.25 s |      22.88 s |    33.37 s |    59.32% |
| `cargo fmt`      |      6.40 s |       7.47 s |    −1.07 s |   −16.75% |

These are measured commands from the complete historical sessions, not separate
microbenchmarks. The slower unchanged check and formatting command remain
included. The historical workload is not part of the three-project headline,
and its whole-session gain cannot be attributed solely to check reuse.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-3 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.28 s |       0.40 s |    −0.12 s |   −44.53% |
| Workspace dependency and root edit |     16.30 s |       7.41 s |     8.89 s |    54.54% |
| Workspace root-only edit           |     15.03 s |       6.75 s |     8.28 s |    55.09% |

## Historical Ruff workflow with Rust 1.98.0 revision 2

The separate [revision 2 historical Ruff replay](release-1.98.0-2-ruff-historical.json)
reruns the historical fixture, including its check-to-test-to-check transitions,
on the same quiet 32-logical-CPU AMD EPYC-Milan host as the current Ruff study,
with eight build jobs. Both counterbalanced repetitions completed with identical
reported test counts and source edits; baseline warmups are excluded.

Both toolchains retain the same narrow `format_push_string` Clippy allowance.
This fixture remains distinct from the current Ruff workflow and is not included
in the headline session aggregate. These measurements compare revision 2 with
stock Rust, not directly with earlier Ohm releases.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-2 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    517.80 s |     374.29 s |   143.51 s |    27.71% |
| `cargo check`    |     45.09 s |      22.32 s |    22.77 s |    50.51% |
| `cargo nextest`  |    393.04 s |     311.60 s |    81.44 s |    20.72% |
| `cargo clippy`   |     71.90 s |      31.58 s |    40.32 s |    56.07% |
| `cargo fmt`      |      7.06 s |       8.10 s |    −1.05 s |   −14.82% |

The individual check transitions are measured commands from the same complete
sessions, not separate microbenchmarks. The slower unchanged check and formatting
command remain included; the whole-session gain cannot be attributed solely to
the check transitions.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-2 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.36 s |       0.46 s |    −0.10 s |   −27.85% |
| Workspace dependency and root edit |     22.64 s |      11.25 s |    11.38 s |    50.29% |
| Workspace root-only edit           |     22.10 s |      10.61 s |    11.49 s |    52.00% |

## Historical Ruff workflow with Rust 1.98.0 revision 1

The separate [Rust 1.98 historical Ruff replay](release-1.98.0-1-ruff-historical.json)
reruns the historical fixture, including its check-to-test-to-check transitions.
Both toolchains use the same narrow allowance for Rust 1.98's new
`format_push_string` lint. Its source revisions and commands remain distinct
from the current Ruff workflow and are not substituted into the headline
session table.

| Scope            | Rust 1.98.0 | Ohm 1.98.0-1 | Time saved | Reduction |
| ---------------- | ----------: | -----------: | ---------: | --------: |
| Complete session |    415.01 s |     292.27 s |   122.73 s |    29.57% |
| `cargo check`    |     33.84 s |      15.56 s |    18.28 s |    54.01% |
| `cargo nextest`  |    317.49 s |     244.59 s |    72.90 s |    22.96% |
| `cargo clippy`   |     56.98 s |      24.64 s |    32.35 s |    56.76% |
| `cargo fmt`      |      6.40 s |       7.19 s |    −0.79 s |   −12.39% |

The individual check transitions below compare this release directly with stock
Rust. They are measured commands from the same complete session, not separate
microbenchmarks; whole-session differences cannot be attributed to these
checks.

| Check transition                   | Rust 1.98.0 | Ohm 1.98.0-1 | Time saved | Reduction |
| ---------------------------------- | ----------: | -----------: | ---------: | --------: |
| Unchanged baseline                 |      0.30 s |       0.42 s |    −0.12 s |   −39.84% |
| Workspace dependency and root edit |     17.50 s |       7.94 s |     9.55 s |    54.61% |
| Workspace root-only edit           |     16.05 s |       7.21 s |     8.84 s |    55.10% |

## Historical Ruff workflow with revision 20

The separate [revision-20 historical Ruff replay](release-1.97.1-20-ruff-historical.json) reruns the unchanged historical fixture, including its check-to-test-to-check transitions. Its source revisions and commands are distinct from the current Ruff workflow and are not substituted into the headline session table.

| Scope            | Rust 1.97.1 | Ohm 1.97.1-20 | Time saved | Reduction |
| ---------------- | ----------: | ------------: | ---------: | --------: |
| Complete session |    420.69 s |      287.33 s |   133.36 s |    31.70% |
| `cargo check`    |     33.68 s |       16.68 s |    17.00 s |    50.46% |
| `cargo nextest`  |    306.64 s |      237.81 s |    68.83 s |    22.45% |
| `cargo clippy`   |     73.73 s |       25.49 s |    48.24 s |    65.43% |
| `cargo fmt`      |      6.38 s |        7.08 s |    −0.70 s |   −11.03% |

The individual check transitions below compare this release directly with stock Rust. They are measured commands from the same complete session, not separate microbenchmarks; whole-session differences cannot be attributed to these checks. Restoring Ohm's earlier check-graph regression was measured against a previous Ohm revision, not against stock Rust.

| Check transition                   | Rust 1.97.1 | Ohm 1.97.1-20 | Time saved | Reduction |
| ---------------------------------- | ----------: | ------------: | ---------: | --------: |
| Unchanged baseline                 |      0.29 s |        0.72 s |    −0.43 s |  −147.34% |
| Workspace dependency and root edit |     17.32 s |        8.24 s |     9.08 s |    52.43% |
| Workspace root-only edit           |     16.07 s |        7.73 s |     8.34 s |    51.92% |

## Historical Ruff workflow with revision 19

The separate [revision-19 historical Ruff replay](release-1.97.1-19-ruff-historical.json) reruns the unchanged historical fixture, including its check-to-test-to-check transitions. Its source revisions and commands are distinct from the current Ruff workflow and are not substituted into the headline session table.

| Scope            | Rust 1.97.1 | Ohm 1.97.1-19 | Time saved | Reduction |
| ---------------- | ----------: | ------------: | ---------: | --------: |
| Complete session |    417.90 s |      407.89 s |    10.01 s |     2.39% |
| `cargo check`    |     33.06 s |       33.78 s |    −0.72 s |    −2.17% |
| `cargo nextest`  |    304.61 s |      315.84 s |   −11.23 s |    −3.69% |
| `cargo clippy`   |     72.98 s |       51.05 s |    21.93 s |    30.05% |
| `cargo fmt`      |      6.36 s |        7.00 s |    −0.64 s |   −10.06% |

The individual check transitions below compare this release directly with stock Rust. They are measured commands from the same complete session, not separate microbenchmarks; whole-session differences cannot be attributed to these checks. Restoring Ohm's earlier check-graph regression was measured against a previous Ohm revision, not against stock Rust.

| Check transition                   | Rust 1.97.1 | Ohm 1.97.1-19 | Time saved | Reduction |
| ---------------------------------- | ----------: | ------------: | ---------: | --------: |
| Unchanged baseline                 |      0.27 s |        0.49 s |    −0.23 s |   −85.35% |
| Workspace dependency and root edit |     16.96 s |       17.24 s |    −0.28 s |    −1.66% |
| Workspace root-only edit           |     15.83 s |       16.04 s |    −0.21 s |    −1.33% |

## Historical Ohm 1.97.1 revision 18 results

The checked-in [historical revision 18 results](release-1.97.1-18-baseline.json) contain all
12 completed samples, source revisions, excluded warmup times, and the exact
public command and both timings for each of the 37 recorded command steps.
Private session identifiers, machine names, and artifact paths are omitted.

The study used the same 32-core Linux host, eight build jobs, pinned source
edits, and stock-first/Ohm-first order as the revision-17 study. Every command
succeeded, and the interference guard observed no competing compilations.
Whole-session times include the three source edits per project and runner
bookkeeping; command-only times exclude those costs. Both include the actual
test execution. Initial checkouts and baseline warmups are not timed.

| Scope                 | Rust 1.97.1 | Ohm 1.97.1-18 | Time saved | Reduction |
| --------------------- | ----------: | ------------: | ---------: | --------: |
| Complete sessions     |  1,041.00 s |      946.00 s |    95.00 s |     9.13% |
| All recorded commands |  1,040.30 s |      945.31 s |    94.99 s |     9.13% |
| Checks and tests only |    755.29 s |      744.68 s |    10.61 s |     1.40% |

The following table breaks the command-only results down by project. Each cell
is the sum of the per-command means across two repetitions. Negative savings
are regressions, and the total reduction is calculated from summed times rather
than averaging project percentages.

| Project / command   | Rust 1.97.1 | Ohm 1.97.1-18 | Time saved | Reduction |
| ------------------- | ----------: | ------------: | ---------: | --------: |
| Ruff / `check`      |     31.02 s |       55.32 s |   −24.30 s |   −78.35% |
| Ruff / `nextest`    |    295.74 s |      302.09 s |    −6.34 s |    −2.15% |
| Ruff / `clippy`     |     70.12 s |       47.89 s |    22.23 s |    31.70% |
| Ruff / `fmt`        |      6.36 s |        7.05 s |    −0.69 s |   −10.90% |
| uv / `test`         |    105.67 s |      106.92 s |    −1.26 s |    −1.19% |
| uv / `clippy`       |     23.59 s |       13.74 s |     9.85 s |    41.75% |
| uv / `fmt`          |     10.15 s |        4.04 s |     6.11 s |    60.16% |
| Codex / `check`     |    133.67 s |      100.30 s |    33.37 s |    24.96% |
| Codex / `just test` |    189.20 s |      180.05 s |     9.15 s |     4.83% |
| Codex / `clippy`    |    174.78 s |      127.89 s |    46.89 s |    26.83% |

Across all projects, tests alone improved by 0.26%, checks and tests together by
1.40%, Clippy by 29.41%, and formatting by 32.80%. In particular, uv's 10.53%
whole-session improvement is not a test-compilation improvement: its test
commands were 1.19% slower. Excluding formatting, its tests and Clippy together
were 6.65% faster.

The historical Ruff commands omit `CARGO_PROFILE_DEV_LTO=off` and usually omit
`--test mdtest`, unlike Ruff's current recommended workflow. The recorded
[`ruff-historical.json`](ruff-historical.json) fixture is retained for
reproducible release comparisons and because it exposed
revision 18's `check` → `nextest` → unchanged `check` graph regression. A newer
Ruff/ty session is measured [above](#ruff-workflow), using the recommended
profile and target selection equally for both toolchains. Its different workload
does not replace these historical measurements.

The devbox's historical wrapper excluded the same 11 host-sensitive or flaky
Codex tests from both toolchains. The final package command reported 3,440 and
3,439 test starts for stock, and 3,439 in both Ohm runs; these small differences
are retained in the data rather than claimed as exact test-count parity. The
full exclusion expression and per-step test counts are included in the results
file. The general `codex.json` fixture does not apply those host-specific
exclusions. To reproduce the recorded selection, make a separate Codex scenario
with the final command from `commands.codex[-1].command` in the results file,
then pass it with `--scenario PATH`. The results also retain checksums of the
original runner and fixtures; the cleaned-up runner in this branch is not
byte-identical to that historical wrapper. Cargo progress messages in this
study do not prove actual rustc invocations; use the separate verbose
attribution mode above for that purpose.

## Historical Ohm 1.97.1 revision 17 baseline

The checked-in [revision 17 baseline](release-1.97.1-17-baseline.json) contains
both repetitions and the exact untimed warmups. The two-run session means were:

| Project | Rust 1.97.1 | Ohm 1.97.1-17 | Improvement |
| ------- | ----------: | ------------: | ----------: |
| Ruff    |    391.75 s |      381.09 s |        2.7% |
| uv      |    137.57 s |      122.59 s |       10.9% |
| Codex   |    491.99 s |      459.41 s |        6.6% |
| Total   |  1,021.32 s |      963.09 s |        5.7% |

The combined check and test commands were 1.3% slower with Ohm. Its net session
improvement came from 23.4% faster Clippy commands and 32.8% faster formatting;
these end-to-end numbers do not demonstrate a general compiler speedup.

The first stock uv warmup was contaminated by a resumed, previously warmed
target. It is excluded from the checked-in cold-start data, while its timed
session remains valid. The historical Ruff fixture intentionally does not prewarm formatting:
its first timed formatter therefore includes cold initialization, matching this
baseline.
Ten Codex snapshots depended on an unrelated host-level Git repository and were
excluded equally from both toolchains; the second repetition also excluded one
independently flaky timing-sensitive test equally from both. The resulting full
suite passed 3,440 and 3,439 distinct tests respectively. Each toolchain incurred
one flaky retry in opposite repetitions. All three sessions were held out from
revision 17's upstream Rust PGO training corpus.

## Feature ablation

The compact uv fixture isolates a real private parser implementation edit. It
rechecks the downstream registry client and reruns focused parser unit tests,
without building the complete uv integration harness:

```sh
python3 scripts/replay_sessions.py \
  --project uv \
  --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv \
  --output-dir /tmp/ohm-feature-ablation \
  --feature-matrix \
  --jobs 8 \
  --require-idle
```

The matrix uses the same Ohm compiler for four combinations: both optimizations
enabled, public API hashing disabled, procedural-macro caching disabled, and
both disabled. Separate target and shared-build directories ensure changing
tracked compiler options never reuses incompatible artifacts. Each combination
warms the same unmodified checkout before applying the identical real edit.

The summary reports each complete edit-and-command workflow and the marginal
effect of each optimization averaged across both states of the other. Positive
benefits indicate time saved; negative benefits indicate net overhead. Check
per-command crate counts in `results.json` to distinguish downstream rebuilds
avoided by public API hashing from direct compilation and macro-caching costs.
Warmup timings are reported separately and excluded from the measured workflow.

```sh
python3 scripts/test_replay_sessions.py
```
