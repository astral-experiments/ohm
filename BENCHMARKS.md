# Benchmark results

We compare each Ohm release with the stock Rust toolchain it builds on. Timings are wall-clock
measurements on x86_64 Linux. The [disk study](#disk-use) ran separately on macOS. To reproduce
the timing measurements, see [Running the benchmarks](#running-the-benchmarks).

## Replayed sessions

Each replay applies the same edits and runs the same commands with both toolchains. We report
the mean elapsed time for each project and sum those means across projects. A complete session
includes the edits, the commands, and the time spent between them.

<!-- benchmark:sessions -->

| Session       | Rust 1.99.0 | Ohm 1.99.0-26 | Time saved |
| ------------- | ----------- | ------------- | ---------- |
| Ruff session  | 405.17 s    | 223.90 s      | 44.74%     |
| uv session    | 135.03 s    | 76.92 s       | 43.03%     |
| Codex session | 359.80 s    | 187.38 s      | 47.92%     |
| ty session    | 199.38 s    | 127.31 s      | 36.14%     |
| All sessions  | 1,099.38 s  | 615.51 s      | 44.01%     |

<!-- /benchmark:sessions -->

### Command timings

These totals group the same four replays by command. A negative saving means Ohm took longer.

<!-- benchmark:commands -->

| Command group                              | Rust 1.99.0 | Ohm 1.99.0-26 | Time saved |
| ------------------------------------------ | ----------- | ------------- | ---------- |
| `cargo check`                              | 100.21 s    | 36.35 s       | 63.73%     |
| `cargo test`, `cargo nextest`, `just test` | 645.98 s    | 429.97 s      | 33.44%     |
| `cargo clippy`                             | 318.57 s    | 118.59 s      | 62.78%     |
| `cargo fmt`                                | 13.82 s     | 8.49 s        | 38.57%     |
| Other commands                             | 19.31 s     | 20.15 s       | −4.39%     |
| All commands                               | 1,097.89 s  | 613.55 s      | 44.12%     |

<!-- /benchmark:commands -->

## Individual edits

These are median times for a single command after an edit. A speedup of 2× means the command
took half as long with Ohm.

### Direct edits

The edit changes the crate being checked, linted, or tested.

<!-- benchmark:direct -->

| Project | Workflow               | Edited crate | Rust 1.99.0 | Ohm 1.99.0-26 | Speedup |
| ------- | ---------------------- | ------------ | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv`         | 1.92 s      | 1.70 s        | 1.13×   |
| uv      | `cargo clippy`         | `uv`         | 3.15 s      | 2.43 s        | 1.29×   |
| uv      | `cargo test --test it` | `uv`         | 16.93 s     | 7.93 s        | 2.14×   |
| Codex   | `cargo check`          | `codex-core` | 2.77 s      | 2.56 s        | 1.08×   |
| Codex   | `just clippy`          | `codex-core` | 13.71 s     | 8.87 s        | 1.55×   |
| Codex   | `just test`            | `codex-core` | 18.35 s     | 17.97 s       | 1.02×   |

<!-- /benchmark:direct -->

### Dependency edits

The edit changes a dependency’s implementation while preserving its public API.

<!-- benchmark:dependency -->

| Project | Workflow               | Edited dependency    | Rust 1.99.0 | Ohm 1.99.0-26 | Speedup |
| ------- | ---------------------- | -------------------- | ----------- | ------------- | ------- |
| uv      | `cargo check`          | `uv-normalize`       | 8.81 s      | 0.45 s        | 19.68×  |
| uv      | `cargo clippy`         | `uv-normalize`       | 12.43 s     | 0.53 s        | 23.27×  |
| uv      | `cargo test --test it` | `uv-normalize`       | 19.64 s     | 2.16 s        | 9.07×   |
| Codex   | `cargo check`          | `codex-utils-string` | 11.64 s     | 0.45 s        | 25.82×  |
| Codex   | `just clippy`          | `codex-utils-string` | 27.77 s     | 0.60 s        | 45.98×  |
| Codex   | `just test`            | `codex-utils-string` | 36.03 s     | 1.78 s        | 20.21×  |

<!-- /benchmark:dependency -->

## Disk use

We measured the space still in use on APFS with the worktrees and build outputs on disk. The
figures include the checkouts, private targets, shared build artifacts, and runtime caches.
The two-worktree figures come from the point when the second worktree finished. The single-session
and ten-worktree figures come from the idle volume. [Disk study](scripts/benchmark_results/disk.json)

<!-- benchmark:disk -->

| Scope                 | Rust 1.99.0 | Ohm 1.99.0-11 | Space saved |
| --------------------- | ----------- | ------------- | ----------- |
| Ruff/ty session       | 5.82 GiB    | 3.49 GiB      | 40.06%      |
| Ruff/ty, 2 worktrees  | 10.07 GiB   | 5.91 GiB      | 41.25%      |
| Ruff/ty, 10 worktrees | 52.98 GiB   | 26.46 GiB     | 50.05%      |
| uv session            | 12.09 GiB   | 7.76 GiB      | 35.83%      |
| uv, 2 worktrees       | 16.25 GiB   | 8.55 GiB      | 47.37%      |
| uv, 10 worktrees      | 79.41 GiB   | 32.31 GiB     | 59.31%      |

<!-- /benchmark:disk -->

## Developer workflows

Each sequence starts after an untimed warmup and keeps build artifacts between commands. The
table shows the median time for four complete runs per toolchain and project.

<!-- benchmark:developer-workflows -->

| Project | Workflow                          | Rust 1.99.0 | Ohm 1.99.0-26 | Time saved |
| ------- | --------------------------------- | ----------- | ------------- | ---------- |
| Ruff/ty | Edit → focused test               | 13.77 s     | 12.07 s       | 12.34%     |
| Ruff/ty | Edit dependency → downstream test | 13.87 s     | 11.86 s       | 14.51%     |
| Ruff/ty | Edit → check → test → check       | 20.41 s     | 19.12 s       | 6.32%      |
| Ruff/ty | Check → build → check             | 74.30 s     | 49.57 s       | 33.28%     |
| Ruff/ty | Edit → fmt → clippy → test        | 26.27 s     | 20.37 s       | 22.48%     |
| uv      | Edit → focused test               | 17.47 s     | 8.57 s        | 50.94%     |
| uv      | Edit dependency → downstream test | 20.93 s     | 2.32 s        | 88.93%     |
| uv      | Edit → check → test → check       | 20.79 s     | 10.89 s       | 47.60%     |
| uv      | Check → build → check             | 112.83 s    | 59.07 s       | 47.65%     |
| uv      | Edit → fmt → clippy → test        | 23.56 s     | 12.40 s       | 47.40%     |
| Codex   | Edit → focused test               | 18.67 s     | 17.32 s       | 7.26%      |
| Codex   | Edit dependency → downstream test | 37.19 s     | 2.23 s        | 94.00%     |
| Codex   | Edit → check → test → check       | 23.63 s     | 22.48 s       | 4.85%      |
| Codex   | Check → build → check             | 111.74 s    | 72.19 s       | 35.40%     |
| Codex   | Edit → fmt → clippy → test        | 26.34 s     | 21.56 s       | 18.13%     |

<!-- /benchmark:developer-workflows -->

## Build reuse, formatting, and worktree startup

These cases measure what Cargo can reuse after a build, how quickly it can format a workspace,
and how long it takes to start a worktree and run its first test.

<!-- benchmark:features -->

| Project | Workflow                 | Package              | Rust 1.99.0 | Ohm     | Speedup |
| ------- | ------------------------ | -------------------- | ----------- | ------- | ------- |
| uv      | Check after build        | `uv`                 | 58.72 s     | 13.02 s | 4.51×   |
| uv      | Shared-worktree build    | `uv-normalize`       | 6.54 s      | 0.64 s  | 10.30×  |
| Codex   | Check after build        | `codex-core`         | 72.67 s     | 20.02 s | 3.63×   |
| Codex   | No-op formatting         | Workspace            | 6.72 s      | 0.08 s  | 85.99×  |
| Codex   | Formatting after an edit | `codex-core`         | 6.52 s      | 0.13 s  | 50.58×  |
| Codex   | Shared-worktree build    | `codex-utils-string` | 1.66 s      | 0.54 s  | 3.10×   |
| ty      | Worktree startup (ext4)  | `ty_python_semantic` | 65.29 s     | 38.27 s | 1.71×   |
| ty      | Worktree startup (Btrfs) | `ty_python_semantic` | 65.22 s     | 37.85 s | 1.72×   |

<!-- /benchmark:features -->

## Documentation tests

We reran Ruff’s documentation examples on unchanged source after an untimed warmup. The table
shows the median of five runs per toolchain.

<!-- benchmark:ruff-doctests -->

| Workload                           | Rust 1.99.0 | Ohm 1.99.0-26 | Speedup |
| ---------------------------------- | ----------- | ------------- | ------- |
| Ruff doctests (`cargo test --doc`) | 13.600 s    | 1.628 s       | 8.35×   |

<!-- /benchmark:ruff-doctests -->

## Running the benchmarks

Compare a tagged Ohm toolchain with its base Rust release on the same quiet host. Use the same
source revisions, job count, and test selection for both toolchains.

### Prerequisites

Install [uv](https://docs.astral.sh/uv/), Git, and both Rust toolchains. Ruff/ty and Codex
workflows need `cargo-nextest`. Codex session replays also need `just`. Run the commands from
the Ohm repository with enough space for separate builds. Cache dependencies before an offline run.

On x86_64 Linux, compare stock Rust 1.99.0 with Ohm 1.99.0-26, which bundles Wild 0.11.0.
The versioned installer checks the archive's SHA-256 against
`ea3504e872eefa119532e8f438326926888030097b25e3519dcf3c5aea28a66b`.
[Ohm installer](https://labs.astral.sh/ohm/releases/ohm-1.99.0-26/install.sh) · [Release manifest](toolchains/1.99.0/26.json)

Run the developer-workflow and individual-command examples below from Ohm commit
`04c83d53483607aec4f93fd2bb55b412f101d677` to use the same drivers, workload revisions and replay
fixtures as the campaign.
[Benchmark drivers and fixtures](https://github.com/astral-sh/ohm/tree/04c83d53483607aec4f93fd2bb55b412f101d677/scripts)

### Run the developer workflows

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
  --ohm ohm-1.99.0-26 \
  --output-dir /path/to/preparation --prepare-only

python3 scripts/benchmark_workflows.py \
  --project uv --source-path uv=/path/to/preparation/sources/uv \
  --upstream 1.99.0 \
  --ohm ohm-1.99.0-26 \
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

### Run the individual-command benchmarks

Run uv and Codex on separate quiet hosts. Select `--project uv` or `--project codex-core`.
Use `--dry-run` to inspect the plan. Both toolchains apply the same edits in
temporary worktrees and use separate target directories.

```console
uv run scripts/benchmark.py \
  --project uv --upstream 1.99.0 --ohm ohm-1.99.0-26 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --minimum-free-gb 60 --quiet-seconds 30 --require-idle \
  --discard-targets --output-dir /path/to/new-empty-results
```

#### Workloads

- **Cold build** starts with an empty target directory.
- **No-op** repeats a command on unchanged source.
- **Direct edit** changes the target crate. **Dependency edit** changes a dependency's implementation while preserving its public API.
- **Build-to-check reuse** times `cargo check` after a build in the same target directory.
- **Incremental formatting** checks Codex formatting on unchanged and edited source.
- **Shared-worktree builds** build a dependency in one worktree, then edit and build it in another. Ohm shares registry artifacts and keeps workspace outputs private.

#### Options

Use `--uv-path` or `--codex-path` to reuse a local checkout and `--uv-rev` or `--codex-rev`
to select a revision. The run-count flags in the example control repetitions. `--discard-targets`
removes build artifacts after each workflow and keeps results and logs. Run
`uv run scripts/benchmark.py --help` for the full list.

### Ruff doctests

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
  --upstream 1.99.0 --ohm ohm-1.99.0-26 --jobs 32 --output /path/to/new-results
```

The results record all five warm pairs, the Cargo, rustc and rustdoc binaries used, and the
test inventory hash. Both priming runs and all ten measured runs passed the same 207 examples
and ignored the same nine. [Ruff doctest measurements](scripts/benchmark_results/ruff-doctests.json)

### Read the results

The individual-command runner writes `summary.md`, `results.json`, and per-command logs. A stock/Ohm
time ratio above 1 means Ohm was faster. Cold builds, build-to-check transitions, and shared-worktree
builds have one sample per toolchain in the example. Use more repetitions to estimate variability.

To replay a recorded development session or measure worktree creation through the first test run,
follow the [session replay guide](scripts/session_replays/README.md) or the
[worktree startup guide](scripts/session_replays/README.md#worktree-startup).

### Recorded measurements

The individual-command benchmarks use the default trust settings. Session replays enable procedural-macro
trust. The ty session, developer workflows, and APFS disk measurements enable both procedural-macro
and native-tool trust. The ty worktree study measures Ohm with and without those opt-ins.

The [results index](scripts/benchmark_results/README.md) links the timings, source revisions,
toolchain settings, disk measurements, and instructions for publishing the results.
