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
python3 scripts/replay_sessions.py \
  --upstream 1.97.1 \
  --ohm ohm-1.97.1-19 \
  --source-path ruff=/path/to/ruff \
  --source-path uv=/path/to/uv \
  --source-path codex=/path/to/codex \
  --output-dir /tmp/ohm-real-session-benchmarks \
  --jobs 8 \
  --repetitions 2 \
  --require-idle
```

Source checkouts are never edited. The runner creates private Git mirrors and
detached worktrees, applies real commit-to-commit patches, and gives each
toolchain its own stable target directory. Baseline warmups populate each
toolchain's target before timed edits begin, making the comparison resemble an
already-active development session. Use `--no-warmup` to measure cold-start
sessions instead. If a public development branch has since been rebased or
deleted, missing replay commits are fetched by their exact pinned full SHAs.

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

```sh
ulimit -n 65536
python3 scripts/replay_sessions.py \
  --project ruff \
  --source-path ruff=/path/to/ruff \
  --upstream 1.97.1 \
  --ohm ohm-1.97.1-19 \
  --output-dir /tmp/ohm-ruff-session-benchmarks \
  --jobs 8 \
  --repetitions 2 \
  --require-idle \
  --background
```

This is the default Ruff replay, alongside `uv.json` and `codex.json`. To
reproduce the older release-comparison workload, pass
`--scenario scripts/session_replays/ruff-historical.json` instead. Its original
edits, commands, and recorded results remain unchanged.

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
