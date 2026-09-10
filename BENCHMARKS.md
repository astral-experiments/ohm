# Running benchmarks

Ohm has two benchmark runners:

- [`scripts/benchmark.py`](scripts/benchmark.py) measures individual build, check, test, and
  formatting workflows in uv and Codex.
- [`scripts/replay_sessions.py`](scripts/replay_sessions.py) replays recorded development sessions
  in Ruff/ty, uv, and Codex. See the [replay guide](scripts/session_replays/README.md).

The [README](README.md) summarizes the published results.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/), Git, and the stock Rust and Ohm toolchains you want to
compare. Codex also needs [`just`](https://github.com/casey/just) and `cargo-nextest`.

Run from the Ohm repository on a quiet machine with enough disk space for separate builds. The
runner may need network access to clone source repositories. Cargo commands run with
`--locked --offline`, so cache their dependencies before starting.

## Run the workflow benchmarks

Preview the plan without cloning or building:

```console
uv run scripts/benchmark.py --upstream 1.98.1 --ohm ohm-1.98.1-2 --dry-run
```

Run both projects:

```console
uv run scripts/benchmark.py \
  --upstream 1.98.1 --ohm ohm-1.98.1-2 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

Change `--upstream` and `--ohm` to select installed toolchains. Use an exact Ohm release name when
you need to reproduce a result, and match its base Rust version with `--upstream`.

The runner creates temporary worktrees at pinned source revisions and gives each workflow and
toolchain its own target directory. It applies reversible edits without changing the source
checkouts. Both toolchains use the same edits, explicit profile settings, job count, and test selection.

### Workloads

- **Cold:** Build from an empty target directory.
- **Dependency edit:** Change a dependency's implementation without changing its public API. uv
  edits `uv-normalize`; Codex edits `codex-utils-string`.
- **Direct edit:** Change the target crate itself: `uv` or `codex-core`.
- **No-op:** Repeat the command without changing source.
- **Build-to-check reuse:** Build the target, then time `cargo check` in the same target directory.
- **Incremental formatting:** Time Codex's formatting check with unchanged and edited source.
- **Shared-worktree builds:** Build a dependency in one worktree, then edit and build it in another.
  Ohm shares registry artifacts through a separate build directory; workspace outputs stay private.

Test workflows build and run one existing test. uv runs the `help::help` integration test against
the CLI; Codex runs a `codex-core` library test.

### Options

- `--project uv` or `--project codex-core`: run one project.
- `--uv-path` and `--codex-path`: use existing source repositories.
- `--uv-rev` and `--codex-rev`: override the pinned source revisions.
- `--cold-runs`, `--noop-runs`, `--dependency-runs`, and `--direct-runs`: set sample counts.
- `--require-idle`: wait for unrelated Rust builds and reject overlapping samples. `--idle-timeout`,
  `--quiet-seconds`, and `--contention-retries` control waiting and retries.
- `--discard-targets`: remove build artifacts after each workflow, keeping results and logs.

The default run uses eight jobs, one cold build, three no-op runs, seven dependency edits, and five
direct edits per core workflow. Run `uv run scripts/benchmark.py --help` for all options.

## Read the results

The output directory contains `summary.md`, `results.json`, and per-command logs. The summary
reports median times and stock/Ohm speedup ratios. A ratio above 1 means Ohm was faster.

Cold builds, build-to-check transitions, and shared-worktree builds use one sample per compiler in
the example above. Treat those ratios as preliminary. Keep slower results in the comparison, and
compare runs with the same sources, tools, profiles, and environment. A comparison against stock
Rust does not isolate changes between Ohm releases.

## Recorded measurements

- [Workflow and disk-usage results](scripts/benchmark_results/)
- [Session fixtures and replay results](scripts/session_replays/)

The result files record the measured versions, source revisions, configuration, and methodology. The
historical macOS/APFS disk studies used a separate volume-allocation meter and worktree schedule;
`benchmark.py` measures elapsed time and does not reproduce those studies.

Ohm 1.98.1 revision 2 results cover [216 workflow samples](scripts/benchmark_results/release-1.98.1-2.json), [12 current-session replays](scripts/session_replays/release-1.98.1-2-baseline.json), [four historical Ruff replays](scripts/session_replays/release-1.98.1-2-ruff-historical.json), and [eight uv ablation replays](scripts/session_replays/release-1.98.1-2-uv-feature-ablation.json). Linux timings compare stock Rust 1.98.1 with Ohm using eight jobs on a 32-CPU AMD EPYC-Milan Processor managed devbox, with Falcon and other infrastructure services enabled.

Each suite passed six five-second preflight checks requiring at least 95% idle, at most 0.5% I/O wait and 0.1% steal, and no unrelated compilers. Continuous monitoring rejects unrelated compilers, intervals with more than 5% host CPU used by other processes belonging to the benchmark user, and three consecutive two-second intervals with more than 5% outside CPU across all users excluding the recorded Falcon service. All service overhead remains in the timings. The runs retain at least 60 GiB of free space. The CPU audit records telemetry for all 428 timed commands, including gaps in their estimated measurement windows.

The [detailed reports](scripts/benchmark_results/README.md) retain the rejected attempts, retries, and audit evidence. All Codex replay cells use the same short, private temporary-directory path configured before warmup.

The uv fixtures leave dev/test debug information unspecified: stock Rust uses full debug information, while Ohm 1.98.1 revision 2 defaults to line tables. Ruff's fixtures explicitly request line tables, and Codex's pinned source explicitly requests limited debug information. The explicit settings are the same across toolchains; the uv comparison includes the released default change. All feature-ablation cells use the same Ohm debug default.

The [APFS study](scripts/benchmark_results/disk-1.98.1-2.json) measures physical allocation across eight cohorts and 44 worktrees. Its [uv fixture](scripts/session_replays/disk-1.98.1-2-uv.json) applies the same test patch to both toolchains. All 404 Cargo commands and 53,664 test executions passed. Another 22 runtime checks passed after measurement. Workspace snapshots were imported into all nine sibling worktrees in each Ohm cohort.

The meter reads native APFS volume allocation and cross-checks it against container allocation. The one- and ten-worktree comparisons use measurements taken after at least 30 seconds idle; the two-worktree comparisons use the checkpoint immediately after the continuation completes. The local study reports physical allocation only.

Allocation-measurement retries and capacity preflights are recorded in the run evidence. The study retained the same workload inputs and 60 GiB runtime reserve throughout. Its paired comparison audit accounts for uv's released debug-default difference.

Replays set `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all`; the APFS study also sets `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all`. These comparisons use each runner's documented configuration against stock Rust and do not isolate individual optimizations or changes between Ohm releases.
