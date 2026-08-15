# Real development-session replays

`scripts/replay_sessions.py` compares stock Rust and Ohm by replaying recorded
development sessions instead of isolated synthetic edits. Each fixture records
an actual session, exact public Git revisions, real source changes, and the
Cargo commands observed between those changes.

The bundled scenarios cover:

- Ruff/ty: inherited-attribute inference changes, focused mdtests, checks,
  Clippy, and package-wide tests.
- uv: the PyPI Simple API JSON parser, parser and registry-client tests,
  Clippy, and a localhost-only installation test.
- Codex: a publicly exported TUI rendering change, focused nextest workflows,
  strict Clippy, and the full TUI package. No private Codex source is required.

Run all three scenarios against existing repository checkouts:

```sh
ulimit -n 65536
python3 scripts/replay_sessions.py \
  --upstream 1.97.1 \
  --ohm ohm-1.97.1-18 \
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

`--source-path ruff=/path/to/huff` supplies Git objects; it does not select the
current `huff` revision or change the recorded commands. A new workload needs a
separate JSON fixture with pinned source revisions, actual edits, commands, and
environment. Keep the existing fixture unchanged when comparing old releases.

## Current Ruff/Huff workflow

[`ruff-huff.json`](ruff-huff.json) records a newer sequence from
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
  --scenario scripts/session_replays/ruff-huff.json \
  --source-path ruff=/path/to/huff \
  --upstream 1.97.1 \
  --ohm ohm-1.97.1-18 \
  --output-dir /tmp/ohm-huff-session-benchmarks \
  --jobs 8 \
  --repetitions 2 \
  --require-idle \
  --background
```

The default `ruff.json` remains the historical release-comparison fixture.
Select `ruff-huff.json` explicitly when measuring the newer workflow.

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

## Ohm 1.97.1 revision 18 results

The checked-in [revision 18 results](release-1.97.1-18-baseline.json) contain all
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
fixture is retained for reproducible release comparisons and because it exposed
revision 18's `check` → `nextest` → unchanged `check` graph regression. A newer
Ruff/ty session should use a separately pinned fixture and apply the recommended
profile and target selection equally to both toolchains. Do not replace these
measurements with numbers from that different workload.

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

## Ohm 1.97.1 revision 17 baseline

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
session remains valid. Ruff's fixture intentionally does not prewarm formatting:
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
