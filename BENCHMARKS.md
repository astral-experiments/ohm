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
uv run scripts/benchmark.py --dry-run
```

Run both projects:

```console
uv run scripts/benchmark.py \
  --upstream 1.98.0 --ohm ohm-1.98.0-8 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

Change `--upstream` and `--ohm` to select installed toolchains. Use an exact Ohm release name when
you need to reproduce a result, and match its base Rust version with `--upstream`.

The runner creates temporary worktrees at pinned source revisions and gives each workflow and
toolchain its own target directory. It applies reversible edits without changing the source
checkouts. Both toolchains use the same edits, profiles, job count, and test selection.

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
