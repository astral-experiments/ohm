# Published benchmarks

We compared published Ohm 1.99.0-22 with stock Rust 1.99.0 on x86_64 Linux. Each project ran both toolchains on the same machine. The four recorded session means totaled 1,742.64 s with Ohm and 1,823.43 s with stock Rust. Ohm took 4.43% less time across the four sessions. [Release results](../1.99.0-22.md) · [Recorded sessions](sessions.json) · [ty session and worktree startup](ty-worktree.md)

The individual-command study covers 216 samples across uv and Codex. The developer study covers five workflows per project for Ruff, uv, and Codex, with four repetitions per toolchain. [Individual commands](workflow.json) · [Developer workflows](developer-workflows.json) · [Historical Ruff replay](historical.json) · [uv feature ablation](ablation.json)

The APFS disk study compares Ohm 1.99.0-11 with stock Rust 1.99.0. All eight cohorts completed in that release. The formatter comparison below measures -10 against -11. [Disk measurements](../disk.json) · [Formatter measurements](../formatting-comparison.json)

The build record identifies each suite’s host, release archive, installed binaries and workload revisions. The ty report includes individual ext4 and Btrfs measurements. [Build provenance](workflow-build.json) · [ty data](ty-worktree.json) · [Trust settings](https://github.com/astral-experiments/ohm/blob/a5882b33dad7d963569bd7a7fe69844164bcbad7/BENCHMARKS.md#recorded-measurements) · [Earlier developer workflows](../1.99.0-9/developer-workflows.md)

The [historical reports and fixtures](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) and [study-specific reproduction inputs](https://github.com/astral-sh/ohm/tree/444cf954135e74a52b4c9f3f6990d0bc6aff1a5a/benchmark-inputs) preserve the earlier workloads and methods. Host assignments and workloads can differ between releases.

The separate [Ruff edited-check study](../ruff-edited-check.json) retains 64 matched pairs for an earlier experimental version of the [public-API metadata optimization](https://github.com/astral-sh/ohm-rust/pull/194), which is included in Ohm 1.99.0-7. Its [build record](../ruff-edited-check-build.json) identifies that experimental compiler. The release tables exclude this earlier study.

## Linux session replays with 1.99.0-22

Each entry gives the wall time in seconds for a complete session replay. The last column compares the mean time for each toolchain on the same host.

| Session         |          Stock Rust 1.99.0 (s) |              Ohm 1.99.0-22 (s) | Time saved |
| --------------- | -----------------------------: | -----------------------------: | ---------: |
| Codex           |                 611.75, 623.73 |             1,082.46, 1,069.30 |    -74.17% |
| Ruff            |                 712.84, 647.14 |                 370.48, 355.39 |     46.63% |
| Ruff historical |                 592.28, 551.03 |                 373.51, 370.88 |     34.89% |
| uv              |                 173.58, 172.99 |                  101.65, 96.15 |     42.93% |
| ty              | 352.65, 355.39, 354.21, 347.46 | 203.09, 204.10, 205.78, 206.73 |     41.85% |

## Ruff compiler and Cargo changes in 1.99.0-15

We changed a diagnostic in Ruff’s parser and timed a rebuild of the workspace on x86_64 Linux. Both compilers used the same Ohm Cargo and linker. The new compiler could reuse downstream crates after the edit. It finished first in all 12 pairs for each command. [Compiler change](https://github.com/astral-sh/ohm-rust/pull/233) · [Paired timings and compiler traces](https://github.com/astral-sh/ohm-cargo/tree/837a3a07a7368c1a3706ab2779b8ab3450814f7d/benchmarks/ruff-dev-loop-20261027/corrected-workspace-parser)

| Command after the edit | Parent Ohm compiler, median | New Ohm compiler, median |
| ---------------------- | --------------------------: | -----------------------: |
| `cargo build`          |                     19.21 s |                   5.60 s |
| `cargo test --no-run`  |                     25.58 s |                   8.24 s |

The second command builds the workspace tests without running them. A separate `cargo check` after a native build failed with both compilers because Cargo selected two incompatible copies of `pep440_rs`. Both compilers passed the check from an empty target directory. [Build-to-check reproducer](https://github.com/astral-sh/ohm-cargo/tree/4ee02e1ceb06050f40fbb43a205612b732b42bbf/benchmarks/ruff-dev-loop-20261027/mixed-native-check)

We also measured Cargo’s own work on a Ruff workspace check with all 520 artifacts up to date. Compared with the prior Ohm Cargo, the Cargo changes in 1.99.0-15 reduced the instruction count in all 12 pairs, with a median reduction of 10.51%. [Cargo measurements and reproduction instructions](https://github.com/astral-sh/ohm-cargo/tree/60f815537745e8dd8867c3062aea061c6865be34/benchmarks/ruff-dev-loop-20261026/ten-cargo-fresh)

## Formatter comparison

We timed `cargo fmt -p <package>` with Ohm 1.99.0-10 and 1.99.0-11 on `charlie-ohm-11-ty`. Each row covers 40 pairs with identical inputs and outputs and a warm cache for each release. We shuffled the order so each release ran first in 20 pairs.

| Project | Formatting case                | -10 median | -11 median | -11 / -10 time (99% CI) |
| ------- | ------------------------------ | ---------: | ---------: | ----------------------: |
| Ruff    | Unchanged file                 |  115.06 ms |  114.07 ms |  1.0009 (0.8914–1.1232) |
| Ruff    | Already formatted comment      |  178.10 ms |  181.84 ms |  1.1382 (0.9760–1.3434) |
| Ruff    | Whitespace requiring a rewrite |  228.99 ms |  239.34 ms |  1.1170 (0.9726–1.3065) |
| uv      | Unchanged file                 |   87.03 ms |  151.70 ms |  1.3260 (1.1025–1.5923) |
| uv      | Already formatted comment      |  831.63 ms |  898.97 ms |  1.0525 (0.9948–1.1167) |
| uv      | Whitespace requiring a rewrite | 1486.13 ms | 1578.68 ms |  1.0680 (1.0370–1.1011) |

The last column gives the geometric mean of the within-pair time ratios. Values above 1 mean -11 took longer. The 99% intervals use 20,000 bootstrap resamples of the pairs. [Paired timings, fixtures, and reproduction instructions](../formatting-comparison.json)

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
