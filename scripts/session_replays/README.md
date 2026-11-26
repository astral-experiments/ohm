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

### Prepare the Codex inputs

For Codex, prepare the frozen inputs once in a dedicated benchmark directory. Both toolchains use the same patched copy of `allocative 0.3.6`. Its published source defines two implementations of the same type on Rust 1.100 development-channel compilers. The helper verifies the crate archive, applies the two upstream source changes and keeps both Codex lockfiles intact. A separate fixture patch sets the workspace `redundant_clone` lint to `warn`. The recorded TUI command still denies `clippy::redundant_closure_for_method_calls`. [Upstream allocative fix](https://github.com/meta/buck2/commit/9711293c6de502d50583cafb12e4a7b764094d3a)

Cargo warns that the path override may have changed the dependency on `allocative_derive`. Both toolchains resolved the same package versions, dependency edges and enabled features with and without the override at each Codex revision. The patched `allocative` itself is a local path dependency.

Run the helper from the Ohm checkout. The Codex source must contain the two recorded revisions. The helper reads the archive from Cargo's cache or from the optional `--archive /path/to/allocative-0.3.6.crate` argument.

```sh
bench_root=/absolute/path/to/codex-benchmark
codex_source=/absolute/path/to/codex
python3 scripts/session_replays/helpers/codex-1.100/prepare.py \
  --benchmark-root "$bench_root" --codex-source "$codex_source"
command_source="$bench_root/compatibility/codex-commands"
command_revision=$(git -C "$command_source" rev-parse HEAD)
```

The helper writes a Cargo path override under `$bench_root/.cargo`. Keep each suite's output beneath that directory so Cargo and Clippy find the override throughout the run. Use these arguments alongside the job count, repetitions and idle controls in the [benchmark guide](../../BENCHMARKS.md).

| Suite                | Source arguments                                                                        | Output argument                         |
| -------------------- | --------------------------------------------------------------------------------------- | --------------------------------------- |
| Individual commands  | `--project codex-core --codex-path "$command_source" --codex-rev "$command_revision"`   | `--output-dir "$bench_root/individual"` |
| Developer workflows  | `--project codex --source-path "codex=$command_source" --codex-rev "$command_revision"` | `--output-dir "$bench_root/developer"`  |
| Recorded TUI session | `--project codex --source-path "codex=$codex_source"`                                   | `--output-dir "$bench_root/session"`    |

## Run the sessions

Choose an installed Ohm release and its corresponding stock Rust version before running the examples.

```sh
stock=1.100.0
ohm=ohm-1.100.0-12
```

```sh
ulimit -n 65536
install -d -m 700 /tmp/ohm-replay-1
export TMPDIR=/tmp/ohm-replay-1
python3 scripts/replay_sessions.py \
  --upstream "$stock" --ohm "$ohm" \
  --source-path ruff=/path/to/ruff \
  --source-path uv=/path/to/uv \
  --source-path "codex=$codex_source" \
  --output-dir "$bench_root/session" \
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

| Project | Fixture                                        | Workload                                                                                               |
| ------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Ruff/ty | [ruff-rust-1.100.json](ruff-rust-1.100.json)   | Recursive attribute inference, focused mdtests, package tests, Clippy, and formatting.                 |
| uv      | [uv-rust-1.100.json](uv-rust-1.100.json)       | PyPI Simple API JSON parsing, parser and registry-client tests, Clippy, and a local installation test. |
| Codex   | [codex-rust-1.100.json](codex-rust-1.100.json) | Public TUI rendering changes, focused nextest runs, package tests, and Clippy.                         |

The default Rust 1.100 fixtures apply the same compatibility patches and Clippy allowances to both toolchains. Profiles and test selections also match. The [historical Ruff fixture](ruff-historical-rust-1.100.json) covers a different session, including check-to-test-to-check transitions. [Archived Rust 1.99 fixtures](https://github.com/astral-experiments/ohm/tree/5ca20614e8ebabc7b3f79a04a9dcc9476e33d882/scripts/session_replays)

The Codex fixture includes a
[test-only setup patch](patches/codex-safety-retry-goal-accounting.patch) that bounds a timing
assertion by elapsed wall time. It keeps the same 11 published host-sensitive or flaky-test
exclusions. No private Codex source is required.

To benchmark a new session, add a fixture with pinned revisions, edits, commands, and environment.
Archive superseded fixtures with their evidence before replacing them. Fixtures can declare hash-pinned
`setup_patches`; the runner verifies and applies them before warmup, then records file hashes and
modes. Setup time is excluded from session and warmup totals.

### ty diagnostic-suppression session

The Rust 1.100 fixture replays the failing mdtests, Markdown and Rust edits, package tests, CLI rebuilds, diagnostic checks, and Clippy from Ruff #29327. It preserves `opt-level = 1` and each command's feature selection. The initial CLI build is untimed. The measured host used cargo-nextest 0.9.140. [Ruff #29327](https://github.com/astral-sh/ruff/pull/29327) · [Rust 1.100 fixture](ty-29327.json)

The build record calls this fixture `ty-29327-rust-1.100.json`. The final Clippy step permits Cargo manifest warnings. We verified its logs against the 56 expected warnings after timing. [Archived warning checker and expected output](https://github.com/astral-experiments/ohm/tree/94f277c4d022c35dde70e10677e75bdec896ac15/scripts/session_replays/helpers/ty-29327)

```sh
python3 scripts/replay_sessions.py \
  --project ruff --scenario scripts/session_replays/ty-29327.json \
  --upstream 1.100.0 --ohm ohm-1.100.0-12 \
  --source-path ruff=/path/to/ruff --output-dir /path/to/new-ty-results \
  --jobs 8 --repetitions 4 --native-tool-trust all \
  --minimum-free-gb 60 --compiler-accounting verbose --offline --require-idle
```

This enables both Ohm trust opt-ins. Expected failures must match the fixture's exit status and diagnostics.

### Worktree startup

[`benchmark_worktree_start.py`](../benchmark_worktree_start.py) builds the focused `liskov.md` test in a parent checkout, then times creating a worktree and running that test there. Parent preparation is excluded.

```sh
python3 scripts/benchmark_worktree_start.py \
  --scenario scripts/session_replays/ty-29327.json \
  --upstream 1.100.0 --ohm ohm-1.100.0-12 \
  --source-path /path/to/ruff --output-dir /path/to/new-worktree-results \
  --jobs 8 --repetitions 3 --minimum-free-gb 60 --compiler-accounting verbose --offline --require-idle
```

The runner compares stock Rust with two Ohm configurations: a shared build directory, and that directory with both trust opt-ins. Each repetition starts with fresh artifacts. Stock Rust uses `git worktree add`; Ohm uses `cargo worktree add`. Snapshot cloning requires a filesystem such as Btrfs; ext4 can still reuse shared registry builds.

For the filesystem comparison, run the worktree command once with an output directory on ext4 and once on Btrfs. Use a fresh output directory after an interrupted startup run. [Session and worktree results](../benchmark_results/ty-worktree.md)

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
  --upstream "$stock" --ohm "$ohm" \
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

The [current reports](../benchmark_results/) retain published measurements; earlier results and fixtures remain in the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts). The [README](../../README.md) shows the headline results.
