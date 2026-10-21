# Running benchmarks

Ohm has four benchmark runners:

- [`scripts/benchmark_workflows.py`](scripts/benchmark_workflows.py) measures complete edit, check,
  build, formatting, lint, and test sequences in Ruff/ty, uv, and Codex.
- [`scripts/benchmark.py`](scripts/benchmark.py) measures individual build, check, test, and
  formatting workflows in uv and Codex.
- [`scripts/replay_sessions.py`](scripts/replay_sessions.py) replays recorded development sessions
  in Ruff/ty, uv, and Codex. See the [replay guide](scripts/session_replays/README.md).
- [`scripts/benchmark_worktree_start.py`](scripts/benchmark_worktree_start.py) measures worktree
  creation and its first test run, starting from a parent that has built the test. See the
  [worktree startup guide](scripts/session_replays/README.md#worktree-startup).

The [README](README.md) summarizes the published results.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/), Git, and the stock Rust and Ohm toolchains you want to
compare. Ruff/ty and Codex workflows and sessions need `cargo-nextest`; Codex session replays also
need [`just`](https://github.com/casey/just).

Run from the Ohm repository on a quiet machine with enough disk space for separate builds. The
runners may need network access to clone source repositories. Workflow benchmarks lock dependencies
and run Cargo offline. Session and worktree replays support `--offline`; cache their dependencies
before enabling it.

## Run the developer workflows

These Linux benchmarks measure five short workflows in the representative projects. The runner
pins each source revision, edit, package, and test selection; `--dry-run` prints the full plan without
cloning or building:

```console
python3 scripts/benchmark_workflows.py --output-dir /path/to/results --dry-run
```

Fetch dependencies before measuring, using the same Cargo home for both commands:

```console
python3 scripts/benchmark_workflows.py \
  --project uv --source-path uv=/path/to/uv \
  --upstream 1.99.0 \
  --ohm ohm-1.99.0-5-uv-fmt-72096bc6b3fc-cargo-5a16c750eba7 \
  --output-dir /path/to/preparation --prepare-only

python3 scripts/benchmark_workflows.py \
  --project uv --source-path uv=/path/to/preparation/sources/uv \
  --upstream 1.99.0 \
  --ohm ohm-1.99.0-5-uv-fmt-72096bc6b3fc-cargo-5a16c750eba7 \
  --jobs 8 --repetitions 4 --contention-retries 8 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

Use `--project ruff` or `--project codex` to run the other projects. Omit `--project` to run all three
sequentially, or assign one project to each devbox. Each project's configurations run sequentially on the same
host. `--workflow` selects a subset for diagnosis. `--resume` retains completed
samples and rejects changed runner code, source definitions, sampling settings, or toolchains. If your shell
sets `PYTHONSAFEPATH=1`, prefix the commands with `env -u PYTHONSAFEPATH`.

The published measurements use eight Cargo jobs on three 32-vCPU Linux devboxes. Each result
records its host metadata, command logs, and CPU traces.

The developer workflows use an optimized experimental build with Rust at
[`72096bc6b3fc`](https://github.com/astral-sh/ohm-rust/commit/72096bc6b3fc4443647fe05deb4ae473b49043f3),
Cargo at [`5a16c750eba7`](https://github.com/astral-sh/ohm-cargo/commit/5a16c750eba7f6b7bcfd7a220a377685c62b3512)
(#176, including #175), and rustfmt at
[`5af2f950cd8b`](https://github.com/astral-sh/ohm-rustfmt/commit/5af2f950cd8bae79cec9ea032885db10e7dfe318).
The [build provenance](scripts/benchmark_results/developer-workflow-build.json) records the component
sources, retained PGO/BOLT inputs, build settings, and binary hashes verified on each machine.
Build these sources and register the toolchain with `rustup toolchain link` before running the commands
above; the regular installer does not provide this experimental build. Use `--ohm` to select another
installed toolchain. See the [results index](scripts/benchmark_results/README.md) for the evidence.

The separate [uv formatter study](scripts/benchmark_results/uv-fmt.json) holds Cargo #176, the compiler,
and optimization inputs constant while comparing rustfmt #27 with its parent. Forty pairs in two
batches, with balanced randomized order, measured a 5.8% paired geometric mean time reduction
(99% bootstrap interval: 4.3–7.2%) for the same edited `cargo fmt -p uv` command. The sample count,
contention rules, and analysis were fixed before candidate timings. Two contention exclusions and
zero execution failures were retained. These pairs are separate from the four-repetition workflow
medians; comparisons with earlier campaigns do not isolate an individual change.

A separate [comment-scan study](scripts/benchmark_results/uv-fmt-comment-scan.json) compares
[rustfmt #33](https://github.com/astral-sh/ohm-rustfmt/pull/33) with #27 on another quiet 32-vCPU devbox.
The rebuilt control formatter is byte-identical to the preceding study's candidate, and only the
rustfmt binary differs between the two new toolchains. The same edited uv command, fixed 40-pair
sample, balanced randomized order, and 99% bootstrap analysis measured a further 14.9% time reduction
(interval: 13.3–16.1%). Two pairs were excluded for contention; no executions failed. Formatted workspace
output was identical, and all 385 formatter tests passed, with one ignored doc test. This follow-up
is separate from the 120 workflow measurements above, which use #27.

The [memchr study](scripts/benchmark_results/uv-fmt-memchr.json) compares the slash searches in #33
with `memchr` across 80 matched pairs, 40 on each of two 32-vCPU devboxes. The fixed sample, balanced
randomized order, and bootstrap stratified by host measured a 0.86% paired geometric mean time
reduction (99% interval: 0.33–1.48%). The host estimates were 0.80% and 0.92%; 13 pairs were excluded
for contention, and no executions failed. Both formatter executables were rebuilt; the compiler,
Cargo #176, sysroot, and optimization inputs were held constant. Formatted workspace output was
identical, subsequent formatting and check commands hit the cache, and all 385 formatter tests
passed, with one ignored doc test. The same patch is published as
[rustfmt #34](https://github.com/astral-sh/ohm-rustfmt/pull/34) above #32; the intervening formatter
changes were not part of this comparison. This study is also separate from the workflow table.

The separate [Ruff edited-check study](scripts/benchmark_results/ruff-edited-check.json) compares an
unreleased compiler with its baseline, holding the Cargo binary and PGO/BOLT inputs constant. On a
16-vCPU host with eight jobs, 64 alternating pairs measured a 3.0% median paired time reduction
(95% bootstrap interval: 1.9–4.1%). Its [build record](scripts/benchmark_results/ruff-edited-check-build.json)
identifies the experimental metadata optimizations from
[Rust #194](https://github.com/astral-sh/ohm-rust/pull/194), which are included in the experimental
developer-workflow build and excluded from the Ohm 1.99.0-6 release benchmarks.

| Workflow                          | Untimed baseline warmup  | Measured sequence                     |
| --------------------------------- | ------------------------ | ------------------------------------- |
| Edit → focused test               | Test                     | Direct edit, test                     |
| Edit dependency → downstream test | Test                     | Dependency implementation edit, test  |
| Edit → check → test → check       | Check, test, check       | Direct edit, check, test, check       |
| Check → build → check             | Check only               | Check, build, check                   |
| Edit → fmt → clippy → test        | Formatting, Clippy, test | Direct edit, formatting, Clippy, test |

The timer covers the entire measured sequence, including applying the edit and runner overhead.
Warmups and source preparation are excluded. Every sample gets fresh target and shared-build
directories, which remain continuous throughout that sample. The runner reverses toolchain order
between repetitions and workflows. Medians are calculated from complete sequences; adding independently
measured command medians would lose the effects of switching commands.

| Project | Target package       | Edited dependency    | Focused test                                                                 |
| ------- | -------------------- | -------------------- | ---------------------------------------------------------------------------- |
| Ruff/ty | `ty_python_semantic` | `ty_python_core`     | `mdtest::liskov.md`, using nextest                                           |
| uv      | `uv`                 | `uv-normalize`       | `help::help` in the `it` integration target                                  |
| Codex   | `codex-core`         | `codex-utils-string` | `preparation_canonicalizes_data_urls_and_rejects_remote_urls`, using nextest |

Check, build, and Clippy target the package's library; formatting applies fixes to the target package. Tests
include compiling and running one existing test. The dependency edits preserve the public API.
Source formatting is normalized with Ohm rustfmt before warmup, identically for each configuration. Both
formatters accept this shared baseline and produce identical formatted edits in the three projects.
Clippy and tests run on the formatted edit in the formatting workflow. Both Ohm trust opt-ins are `all` and its
shared build directory is separate from the target directory. The uv default-debug-information
difference remains part of the stock/Ohm comparison; explicit project profiles are preserved.

With `--require-idle`, each sample waits after its baseline warmup for 30 seconds with at least 95%
host CPU idle, at most 0.5% I/O wait and 0.1% steal, and no unrelated compilers. During measurement,
the runner rejects unrelated compilers, steal above 0.1%, or three consecutive two-second samples
with more than 5% host CPU used by other processes. It also rejects unrelated compilation during
warmup. Host CPU counters include competing processes that finish between samples. Background
monitoring services remain enabled and their overhead remains in the timings.
Attempts rejected by the activity checks retain logs and build state and are retried from fresh artifacts. If a run
exhausts its attempts, resume it with a larger `--contention-retries` value; existing attempts are
skipped and their evidence is preserved.

A command with an unexpected exit status is retained as a failed execution, and the runner continues
with the remaining workflows. It keeps the failed build state and copies compiler crash reports into
the logs. The process exits unsuccessfully after completing the study if any executions failed.
Missing tools and other setup errors still stop the run. `--resume` skips both successful and failed
executions; a failed execution is never retried to obtain a better timing.

The result directory contains `results.json` and per-command logs and CPU traces. To validate and
combine the three completed runs:

```console
python3 scripts/workflow_results.py /path/to/ruff/results.json /path/to/uv/results.json \
  /path/to/codex/results.json --output /path/to/developer-workflows.json
```

The report retains each sequence and command timing, warmups, source identities, compiler revisions,
executable and compiler-library hashes, failed executions, and rejected attempts. If any repetition
fails, the table shows a failure count
for that toolchain and omits its timing and the row's speedup. Archive the raw evidence and
save the validated report as `scripts/benchmark_results/developer-workflows.json`, then
refresh the README table:

```console
python3 scripts/publish_benchmarks.py --render
```

## Run the individual-command benchmarks

Preview the plan without cloning or building:

```console
uv run scripts/benchmark.py --upstream 1.99.0 --ohm ohm-1.99.0-6 --dry-run
```

Run both projects:

```console
uv run scripts/benchmark.py \
  --upstream 1.99.0 --ohm ohm-1.99.0-6 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

Change `--upstream` and `--ohm` to select installed toolchains. Use an exact Ohm release name when
you need to reproduce a result, and match its base Rust version with `--upstream`.

The runner creates temporary worktrees at pinned source revisions and gives each workflow and
toolchain its own target directory. It applies reversible edits without changing the source
checkouts. All configurations use the same edits, explicit profile settings, job count, and test selection.

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

- [ty bug-fix session and worktree startup](scripts/benchmark_results/ty-worktree.md)
- [Workflow and disk-usage results](scripts/benchmark_results/)
- [Session fixtures and replay results](scripts/session_replays/)

The reports record toolchain versions, sources, profiles, individual timings, and measurement conditions. Their evidence links contain logs, CPU traces, and excluded attempts.

The release timing studies compare stock Rust 1.99.0 with Ohm 1.99.0-6, using eight Cargo jobs on
32-CPU Linux devboxes. uv and Codex each use a dedicated host. Ruff's main replay uses a third
host; its historical replay uses the host that completed the ty study. The experimental developer
workflows use three separate 32-CPU hosts, one per project, with eight jobs. Every comparison keeps
all configurations and repetitions on one host. Host and CPU identities are recorded in each report;
these measurements do not isolate changes from earlier Ohm releases.

Individual-command runs leave both trust opt-ins unset. Session replays set procedural-macro trust
to `all`; the ty session and developer workflows also set native-tool trust to `all`.
Linux runs retain full-VM CPU and process traces and require at least 60 GiB free during measurement.

The [APFS study](scripts/benchmark_results/disk.json) measures physical disk allocation on macOS, with both Ohm trust opt-ins set to `all`. Each cohort uses an isolated volume. Its source, tests, artifact isolation, and allocation are checked before the volume is removed; the evidence archive retains those checks. These measurements make no claim about elapsed time on the Mac.

Earlier reports and fixtures remain in the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts). These measurements do not isolate changes between Ohm releases.
