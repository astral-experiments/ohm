# Replaying development sessions

[`scripts/replay_sessions.py`](../replay_sessions.py) compares stock Rust and Ohm using recorded
development sessions. Fixtures pin public Git revisions, source edits, and the commands run between
edits. The runner creates private mirrors and worktrees, leaving source checkouts untouched.

## Prerequisites

Run from the Ohm repository with Python 3.11 or later, Git, and both Rust toolchains installed. Ruff
and Codex require `cargo-nextest`; Codex also requires `just`. The uv installation test requires
Python 3.12.

Use a quiet host and allow disk space for separate worktrees and build artifacts. Codex's test graph
can exceed the default file-descriptor limit. It also needs a short, private temporary directory:
two tests depend on path length or its encoded representation. A symlink to a longer path does not
work.

## Run the sessions

```sh
ulimit -n 65536
install -d -m 700 /tmp/ohm-replay-1
export TMPDIR=/tmp/ohm-replay-1
python3 scripts/replay_sessions.py \
  --upstream 1.98.1 \
  --ohm ohm-1.98.1-2 \
  --scenario scripts/session_replays/ruff-rust-1.98.json \
  --scenario scripts/session_replays/codex-stable-goal-accounting.json \
  --source-path ruff=/path/to/ruff \
  --source-path uv=/path/to/uv \
  --source-path codex=/path/to/codex \
  --output-dir /path/to/new-empty-results \
  --jobs 8 \
  --repetitions 2 \
  --require-idle
```

Add `--dry-run` to inspect the selected fixtures and commands without running them. It still
prepares private source mirrors and may fetch missing commits. Change `--upstream` and `--ohm` to
select installed toolchains. Use an exact Ohm release name for reproducible results, paired with its
base Rust version.

`--source-path` supplies Git objects from an existing checkout; it does not select that checkout's
current revision. The runner fetches missing pinned commits if needed. Replay commands run online by
default. Add `--offline` only after caching the required dependencies.

If your shell sets `PYTHONSAFEPATH=1`, invoke the trusted script with
`env -u PYTHONSAFEPATH python3 scripts/replay_sessions.py ...` so it can import its sibling
`benchmark.py` module.

### Select a fixture

Use `--project ruff`, `--project uv`, or `--project codex` to run one project. Override its fixture
with `--scenario PATH`.

| Project | Fixture                                                                | Workload                                                                                               |
| ------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Ruff/ty | [ruff-rust-1.98.json](ruff-rust-1.98.json)                             | Recursive attribute inference, focused mdtests, package tests, Clippy, and formatting.                 |
| uv      | [uv.json](uv.json)                                                     | PyPI Simple API JSON parsing, parser and registry-client tests, Clippy, and a local installation test. |
| Codex   | [codex-stable-goal-accounting.json](codex-stable-goal-accounting.json) | Public TUI rendering changes, focused nextest runs, package tests, and Clippy.                         |

The Ruff fixture allows `clippy::format_push_string`, which Rust 1.98 introduced after the recorded
source revision. Both toolchains use the same allowance, profile, and test selection. The older
[ruff-historical-rust-1.98.json](ruff-historical-rust-1.98.json) fixture covers a different session,
including check-to-test-to-check transitions.

The Codex fixture includes a
[test-only setup patch](patches/codex-safety-retry-goal-accounting.patch) that bounds a timing
assertion by elapsed wall time. It keeps the same 11 published host-sensitive or flaky-test
exclusions. No private Codex source is required.

To benchmark a new session, add a fixture with pinned revisions, edits, commands, and environment.
Keep existing fixtures stable so old results remain reproducible. Fixtures can declare hash-pinned
`setup_patches`; the runner verifies and applies them before warmup, then records file hashes and
modes. Setup time is excluded from session and warmup totals.

### ty diagnostic-suppression session

[`ty-29327.json`](ty-29327.json) replays [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327).
It builds the ty executable, checks two Python reproducers, adds and expands Markdown regressions,
runs two expected failing mdtests, applies the Rust fix, runs focused and package tests, rebuilds ty,
checks 24 baseline/fixed diagnostic results, and runs Clippy with all targets and features.
The three edit patches reproduce the public PR exactly.

The baseline CLI build is warmed before timing. The replay preserves `opt-level = 1` and the
different feature selections of the CLI, semantic tests, and Clippy. It disables snapshot mutation
for both toolchains. The Python helper replaces machine-specific paths and the original `uv run`
launcher; its baseline step includes copying the saved executable. Expected failures require both
the recorded exit status and diagnostic assertions, so a compiler failure cannot count as a red test.

```sh
python3 scripts/replay_sessions.py \
  --project ruff --scenario scripts/session_replays/ty-29327.json \
  --upstream 1.99.0 --ohm ohm-1.99.0-3 \
  --source-path ruff=/path/to/ruff --output-dir /path/to/new-ty-results \
  --jobs 8 --repetitions 4 --native-tool-trust all --require-idle
```

`--native-tool-trust all` adds authenticated native-tool reuse to the runner's existing
procedural-macro trust opt-in. This matches the local development configuration used for the
recorded session; it is additional to packaged defaults. Existing fixtures and results remain unchanged.

See the [Ohm 1.99.0-3 measurements](../benchmark_results/ty-worktree-1.99.0-3.md) for timings,
compiler counts, and source and test checks.

### Worktree startup

[`benchmark_worktree_start.py`](../benchmark_worktree_start.py) measures a separate transition:
warm the unmodified parent checkout with the focused `liskov.md` mdtest, create a worktree at the
same revision, then run that validation for the first time in its private target directory.
The parent warmup is reported separately. Creation and first-validation times are reported
individually and summed; source checks between them are excluded.

```sh
python3 scripts/benchmark_worktree_start.py \
  --upstream 1.99.0 --ohm ohm-1.99.0-3 \
  --source-path /path/to/ruff --output-dir /path/to/new-worktree-results \
  --jobs 8 --repetitions 3 --require-idle
```

Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add` to seed compatible state from
the parent. Both keep workspace outputs private. The runner measures Ohm with a separate shared
build directory, then with both local trust opt-ins set to `all`. Each configuration and repetition
starts with fresh parent, child, and shared build directories. The order rotates between repetitions.
Snapshot seeding requires copy-on-write file cloning. Cargo reports skipped profiles when the
filesystem cannot clone them; shared registry artifacts can still reduce the first build's work.
The result measures first-validation latency on the host filesystem, not APFS disk savings or a
warm edit/retest loop. Interrupted attempts need a new output directory.

### Warmups and toolchain settings

By default, untimed baseline warmups populate each toolchain's target directory before edits begin.
Use `--no-warmup` to include cold compilation. Repetitions alternate order: stock then Ohm, followed
by Ohm then stock.

The Ohm configuration enables a separate shared build directory and
`CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all`. This trust opt-in is potentially unsound, so the results
include settings beyond packaged defaults. `--no-shared-build` disables the shared directory; it
does not disable procedural-macro trust.

### Background runs and recovery

Use `--background` to continue after an SSH disconnect. The output directory contains `run.log` and
`status.json`.

After an interruption, rerun with `--resume` and identical options. Completed samples are kept.
Incomplete samples restart with fresh worktrees and build artifacts; interrupted files are saved
under `interrupted/<project>/<toolchain>/<repetition>/<attempt>/`. Changes to fixtures, setup
patches, or environment require a new output directory.

`--require-idle` waits for unrelated compilers and rejects samples that overlap them.
`--idle-timeout` controls the maximum wait. Run `python3 scripts/replay_sessions.py --help` for all
options.

## Compare individual features

The uv ablation fixture applies a private parser edit, checks downstream `uv-client`, and runs
focused parser tests. It compares four combinations on the same Ohm compiler: both optimizations
enabled, public API hashing disabled, procedural-macro caching disabled, and both disabled.

```sh
python3 scripts/replay_sessions.py \
  --project uv \
  --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv \
  --upstream 1.98.1 \
  --ohm ohm-1.98.1-2 \
  --output-dir /path/to/new-empty-ablation-results \
  --feature-matrix \
  --jobs 8 \
  --repetitions 2 \
  --require-idle
```

Each combination gets separate target and shared-build directories and warms the same unmodified
checkout before applying the edit. Results report the complete edit-and-command workflow and each
feature's effect averaged across both settings of the other feature. Positive values mean time
saved; negative values mean overhead. These results describe this fixture, not other workloads or
individual patches within an Ohm release.

## Interpret the output

`results.json` contains session and per-command timings alongside run metadata. Full-session times
include edits and runner overhead; command totals exclude them. Baseline warmups are reported
separately. Two repetitions provide preliminary estimates, not confidence intervals.

Check the per-command logs for failures, retries, and selected tests. `tests_started` counts
test-runner output, including retries; it is not a count of unique selected tests. Keep rejected
runs and slower results when recording a comparison, and record the toolchain versions, helper
versions, fixtures, and environment.

Cargo's `Checking` and `Compiling` messages are counted as `cargo_reported_crates`. They do not
prove that rustc ran: early cutoff can skip compilation after a status message appears.

For compiler counts, add `--compiler-accounting verbose`. This sets `CARGO_TERM_VERBOSE=true` for
both toolchains and counts `rustc` and `clippy-driver` executions from Cargo's `Running` commands. A
status message without compilation can mean early cutoff or a build-script-only action; inspect the
log to distinguish them. Verbose output adds overhead, so compare it only with other verbose runs
and use the default mode for headline timings.

Recorded release results are stored alongside these fixtures as `release-*-*.json`. The
[README](../../README.md) shows the headline results; the [benchmark guide](../../BENCHMARKS.md)
covers individual workflows.
