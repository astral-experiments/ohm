# Running benchmarks

Compare a tagged Ohm toolchain with its base Rust release on the same quiet host. Use the same
source revisions, job count, and test selection for both toolchains.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/), Git, and both Rust toolchains. Ruff/ty and Codex
workflows need `cargo-nextest`. Codex session replays also need `just`. Run the commands from
the Ohm repository with enough space for separate builds. Cache dependencies before an offline run.

On x86_64 Linux, compare stock Rust 1.99.0 with Ohm 1.99.0-23, which bundles Wild 0.11.0.
The versioned installer checks the archive's SHA-256 against
`163267d26889b1bd2c467d7db97efee42cd2ac9dc9af2abc3a56ade8da9a9572`.
[Ohm installer](https://labs.astral.sh/ohm/releases/ohm-1.99.0-23/install.sh) · [Release manifest](toolchains/1.99.0/23.json)

Run the examples below from Ohm commit `04c83d53483607aec4f93fd2bb55b412f101d677` to use the
same benchmark drivers, workload revisions and replay fixtures as the campaign.
[Benchmark drivers and fixtures](https://github.com/astral-sh/ohm/tree/04c83d53483607aec4f93fd2bb55b412f101d677/scripts)

## Run the developer workflows

The Linux runner measures five command sequences. Each repetition starts with fresh build
artifacts and keeps them between commands. The timer starts after warmup and includes the edit.
The runner alternates toolchain order. Use `--dry-run` to see the pinned revisions and commands.

| Workflow                          | Untimed baseline warmup  | Measured sequence                     |
| --------------------------------- | ------------------------ | ------------------------------------- |
| Edit → focused test               | Test                     | Direct edit, test                     |
| Edit dependency → downstream test | Test                     | Dependency implementation edit, test  |
| Edit → check → test → check       | Check, test, check       | Direct edit, check, test, check       |
| Check → build → check             | Check only               | Check, build, check                   |
| Edit → fmt → clippy → test        | Formatting, Clippy, test | Direct edit, formatting, Clippy, test |

Prepare the sources and dependencies, then measure with the same Cargo home in both steps.

```console
python3 scripts/benchmark_workflows.py \
  --project uv --source-path uv=/path/to/uv \
  --upstream 1.99.0 \
  --ohm ohm-1.99.0-23 \
  --output-dir /path/to/preparation --prepare-only

python3 scripts/benchmark_workflows.py \
  --project uv --source-path uv=/path/to/preparation/sources/uv \
  --upstream 1.99.0 \
  --ohm ohm-1.99.0-23 \
  --jobs 8 --repetitions 4 --contention-retries 8 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

Choose `--project ruff`, `uv`, or `codex`, or omit the option to run all three. Use
`--workflow` to select one sequence. If your shell sets `PYTHONSAFEPATH=1`, prefix the commands
with `env -u PYTHONSAFEPATH`.

| Project                           | Target package       | Edited dependency    | Focused test                                                                 |
| --------------------------------- | -------------------- | -------------------- | ---------------------------------------------------------------------------- |
| [Ruff/ty at 4d6a7db][ruff-source] | `ty_python_semantic` | `ty_python_core`     | `mdtest::liskov.md`, using nextest                                           |
| [uv at c22e6b7][uv-source]        | `uv`                 | `uv-normalize`       | `help::help` in the `it` integration target                                  |
| [Codex at 5157493][codex-source]  | `codex-core`         | `codex-utils-string` | `preparation_canonicalizes_data_urls_and_rejects_remote_urls`, using nextest |

[ruff-source]: https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6
[uv-source]: https://github.com/astral-sh/uv/commit/c22e6b71933443e9cd299d4b6ac8de035ed4825b
[codex-source]: https://github.com/openai/codex/commit/5157493c23713ac12034cf250ffb0a8ce0670277

The direct edit changes the target package. The dependency edit preserves its public API.
The formatting workflow starts both toolchains from the same normalized source, then runs
Clippy and the focused test on the formatted edit.

With `--require-idle`, the runner waits for 30 seconds with at least 95% host CPU idle, at most
0.5% I/O wait and 0.1% steal, and no unrelated compilers. It rejects unrelated compilation during
warmup or measurement. It also rejects measurements with CPU steal above 0.1% or external CPU use
above 5% for three consecutive two-second samples.

A contention retry starts the sequence from fresh artifacts. If a sequence exhausts its retries, use
`--resume` and raise `--contention-retries`. The runner keeps completed samples, rejected
attempts, and their logs. It records unexpected command failures and continues with the remaining
workflows. If a repetition fails, the table omits that toolchain's median and the workflow's speedup.

Combine the three projects' results to calculate medians from complete sequences.

```console
python3 scripts/workflow_results.py /path/to/ruff/results.json /path/to/uv/results.json \
  /path/to/codex/results.json --output /path/to/developer-workflows.json
```

## Run the individual-command benchmarks

Run uv and Codex on separate quiet hosts. Select `--project uv` or `--project codex-core`.
Use `--dry-run` to inspect the plan. Both toolchains apply the same edits in
temporary worktrees and use separate target directories.

```console
uv run scripts/benchmark.py \
  --project uv --upstream 1.99.0 --ohm ohm-1.99.0-23 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --minimum-free-gb 60 --quiet-seconds 30 --require-idle \
  --discard-targets --output-dir /path/to/new-empty-results
```

### Workloads

- **Cold build** starts with an empty target directory.
- **No-op** repeats a command on unchanged source.
- **Direct edit** changes the target crate. **Dependency edit** changes a dependency's implementation while preserving its public API.
- **Build-to-check reuse** times `cargo check` after a build in the same target directory.
- **Incremental formatting** checks Codex formatting on unchanged and edited source.
- **Shared-worktree builds** build a dependency in one worktree, then edit and build it in another. Ohm shares registry artifacts and keeps workspace outputs private.

### Options

Use `--uv-path` or `--codex-path` to reuse a local checkout and `--uv-rev` or `--codex-rev`
to select a revision. The run-count flags in the example control repetitions. `--discard-targets`
removes build artifacts after each workflow and keeps results and logs. Run
`uv run scripts/benchmark.py --help` for the full list.

## Ruff doctests

This benchmark times `cargo test --doc --all-features --locked --offline` on 16 crates from
[Ruff revision `23a16fa`](https://github.com/astral-sh/ruff/tree/23a16fa018cf3b219c2edc7a2b739881e023a874).
Each toolchain starts with its own empty target directory. The first run primes it. We then time
five pairs, alternating which toolchain runs first, and report each toolchain’s median. The
runner checks every example’s crate, name, and outcome against the first run.

On a quiet x86-64 Linux host, install both toolchains and run the following from the Ohm checkout.
`--source` must point to a clean checkout of the pinned Ruff revision.

```console
cargo +1.99.0 fetch --locked --manifest-path /path/to/ruff/Cargo.toml
python3 scripts/benchmark_ruff_doctests.py --source /path/to/ruff \
  --upstream 1.99.0 --ohm ohm-1.99.0-23 --jobs 32 --output /path/to/new-results
```

The results record all five warm pairs, the Cargo, rustc and rustdoc binaries used, and the
test inventory hash. Both priming runs and all ten measured runs passed the same 207 examples
and ignored the same nine. [Ruff doctest measurements](scripts/benchmark_results/ruff-doctests.json)

## Read the results

The individual-command runner writes `summary.md`, `results.json`, and per-command logs. A stock/Ohm
time ratio above 1 means Ohm was faster. Cold builds, build-to-check transitions, and shared-worktree
builds have one sample per toolchain in the example. Use more repetitions to estimate variability.

To replay a recorded development session or measure worktree creation through the first test run,
follow the [session replay guide](scripts/session_replays/README.md) or the
[worktree startup guide](scripts/session_replays/README.md#worktree-startup).

## Recorded measurements

The individual-command benchmarks use the default trust settings. Session replays enable procedural-macro
trust. The ty session, developer workflows, and APFS disk measurements enable both procedural-macro
and native-tool trust. The ty worktree study measures Ohm with and without those opt-ins.

The [results index](scripts/benchmark_results/README.md) links the timings, source revisions,
toolchain settings, disk measurements, and instructions for publishing the README tables.
