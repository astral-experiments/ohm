# Published benchmarks

We compared published Ohm 1.99.0-26 with stock Rust 1.99.0 on x86_64 Linux. Each project ran both toolchains on the same machine. The four recorded session means totaled 615.51 s with Ohm and 1,099.38 s with stock Rust. Ohm took 44.01% less time across the four sessions. [Release results](1.99.0-26.md) · [Slower replay steps](1.99.0-26.md#slower-replay-steps) · [Recorded sessions](sessions.json) · [ty session and worktree startup](ty-worktree.md)

The individual-command study covers 216 samples across uv and Codex. The developer study covers five workflows per project for Ruff, uv, and Codex, with four repetitions per toolchain. [Individual commands](workflow.json) · [Developer workflows](developer-workflows.json) · [Historical Ruff replay](historical.json) · [uv feature ablation](ablation.json)

The [Ruff doctest study](../../BENCHMARKS.md#ruff-doctests) measures repeated test runs. The [APFS disk study](disk.json) compares Ohm 1.99.0-11 with stock Rust 1.99.0.

The [build record](workflow-build.json) identifies each suite’s host, release archive, installed binaries, and workload revisions. See the [ty measurements](ty-worktree.json) for ext4 and Btrfs results and the [benchmark guide](../../BENCHMARKS.md#recorded-measurements) for the trust settings used in each study.

## Linux session replays with 1.99.0-26

Each entry gives the wall time in seconds for a complete session replay. The last column compares the mean time for each toolchain on the same host.

| Session         |          Stock Rust 1.99.0 (s) |              Ohm 1.99.0-26 (s) | Time saved |
| --------------- | -----------------------------: | -----------------------------: | ---------: |
| Codex           |                 361.33, 358.26 |                 186.56, 188.20 |     47.92% |
| Ruff            |                 406.93, 403.42 |                 224.12, 223.67 |     44.74% |
| Ruff historical |                 399.79, 400.12 |                 251.85, 251.21 |     37.11% |
| uv              |                 136.65, 133.42 |                   76.76, 77.09 |     43.03% |
| ty              | 204.53, 198.70, 195.87, 198.40 | 125.41, 126.82, 128.73, 128.30 |     36.14% |

## Earlier studies

Earlier release reports and one-off experiments are in the [benchmark archive](https://github.com/astral-experiments/ohm/tree/a2deb1cf5ce3a40bd6673b92b90a58d425514b3d/scripts/benchmark_results), including the [Ruff compiler and Cargo study](https://github.com/astral-experiments/ohm/blob/a2deb1cf5ce3a40bd6673b92b90a58d425514b3d/scripts/benchmark_results/README.md#ruff-compiler-and-cargo-changes-in-1990-15) and the [formatter comparison](https://github.com/astral-experiments/ohm/blob/a2deb1cf5ce3a40bd6673b92b90a58d425514b3d/scripts/benchmark_results/README.md#formatter-comparison). The [earlier reports and fixtures](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) and [study-specific reproduction inputs](https://github.com/astral-sh/ohm/tree/444cf954135e74a52b4c9f3f6990d0bc6aff1a5a/benchmark-inputs) preserve the original workloads.

## Publish results

Commit the individual measurements, toolchain and source revisions, workload fixtures, and reasons for excluding runs. Keep command logs and CPU traces through review. Include a trace in Git when a published conclusion depends on it.

Prepare audited reports named `workflow.json`, `sessions.json`, `historical.json`, and `ablation.json`. Supply `disk.json` when the release has new disk measurements. Otherwise, the publisher keeps the checked-in disk report and labels the disk comparison with the toolchains used in that study.

Record the ty measurements in `ty-worktree.json` and `ty-worktree.md`. Combine the three developer-workflow runs with `scripts/workflow_results.py` and save the validated `developer-workflows.json`.

Install formatting dependencies with `npm ci --ignore-scripts` and run the publisher locally.

```console
python3 scripts/publish_benchmarks.py /path/to/audited-reports
```

The publisher checks versions, sample counts, test counts, and arithmetic before writing the reports and tables. It refuses to replace the current release's results. After updating a separately measured developer-workflow report, use `--render` to refresh the tables. CI verifies them offline with the same command you can use locally.

```console
python3 scripts/publish_benchmarks.py --check
```
