# Published benchmarks

We compared published Ohm 1.99.0-15 with stock Rust 1.99.0 on x86_64 Linux. Each project ran both toolchains on the same machine. The four recorded session means totaled 1,029.18 s with Ohm and 1,941.52 s with stock Rust, a 46.99% reduction. Some steps took longer with Ohm. The uv registry-client unit tests averaged 7.84 s with Ohm and 7.06 s with stock Rust. The uv workspace formatting check averaged 3.64 s and 3.59 s, respectively. [Recorded sessions](sessions.json) · [ty session and worktree startup](ty-worktree.md)

The individual-command study includes 216 accepted samples across uv and Codex. The largest difference was a Codex Clippy run after an edit to `codex-utils-string`. Its median fell from 50.05 s to 1.39 s. The ten completed developer workflows for Ruff and Codex appear below. The README’s developer-workflow table still shows 1.99.0-14 while the five uv comparisons for 1.99.0-15 are in progress. [Individual commands](workflow.json) · [Historical Ruff replay](historical.json) · [uv feature ablation](ablation.json)

Host activity invalidated 32 samples in the first uv individual-command trial. The replacement supplied all 100 accepted uv samples. Two uv developer-workflow trials stopped after 17 and 29 samples. We excluded both trials and resumed the missing cells on a separate host. The Codex and Ruff developer runs discarded 14 and five attempts, respectively. The ty report records its exclusions separately. [ty audit](ty-worktree.json)

The APFS disk study compares Ohm 1.99.0-11 with stock Rust 1.99.0. All eight cohorts completed in that release. The formatter comparison below measures -10 against -11. [Disk measurements](disk.json) · [Formatter measurements](formatting-comparison.json)

The build record identifies each suite’s host, release archive, installed binaries and workload revisions. The ty report includes individual ext4 and Btrfs measurements. [Build provenance](workflow-build.json) · [ty data](ty-worktree.json) · [Trust settings](../../BENCHMARKS.md#recorded-measurements) · [Earlier developer workflows](1.99.0-9/developer-workflows.md)

The [historical reports and fixtures](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) and [study-specific reproduction inputs](https://github.com/astral-sh/ohm/tree/444cf954135e74a52b4c9f3f6990d0bc6aff1a5a/benchmark-inputs) preserve the earlier workloads and methods. Host assignments and workloads can differ between releases.

The separate [Ruff edited-check study](ruff-edited-check.json) retains 64 matched pairs for an earlier experimental version of the [public-API metadata optimization](https://github.com/astral-sh/ohm-rust/pull/194), which is included in Ohm 1.99.0-7. Its [build record](ruff-edited-check-build.json) identifies that experimental compiler. The release tables exclude this earlier study.

## Linux session replays with 1.99.0-15

Each entry gives the wall time in seconds for a complete session replay. The last column compares the mean time for each toolchain on the same host.

| Session         |          Stock Rust 1.99.0 (s) |              Ohm 1.99.0-15 (s) | Time saved |
| --------------- | -----------------------------: | -----------------------------: | ---------: |
| Codex           |                 706.38, 611.08 |                 332.57, 340.19 |     48.93% |
| Ruff            |                 529.11, 505.25 |                 282.47, 280.71 |     45.55% |
| Ruff historical |                 484.48, 494.34 |                 321.58, 326.49 |     33.79% |
| uv              |                 156.32, 159.12 |                   91.71, 90.05 |     42.38% |
| ty              | 660.37, 601.37, 635.72, 534.12 | 332.38, 327.47, 312.86, 308.63 |     47.30% |

### Completed developer workflows

Each median covers four complete workflows per toolchain.

| Project | Workflow                          | Stock Rust 1.99.0 | Ohm 1.99.0-15 | Time saved |
| ------- | --------------------------------- | ----------------: | ------------: | ---------: |
| Ruff/ty | Edit → focused test               |           16.20 s |       14.56 s |     10.09% |
| Ruff/ty | Edit dependency → downstream test |           16.46 s |       12.47 s |     24.24% |
| Ruff/ty | Edit → check → test → check       |           24.19 s |       22.41 s |      7.37% |
| Ruff/ty | Check → build → check             |           92.34 s |       58.94 s |     36.17% |
| Ruff/ty | Edit → fmt → clippy → test        |           31.88 s |       23.96 s |     24.84% |
| Codex   | Edit → focused test               |           31.51 s |       23.57 s |     25.21% |
| Codex   | Edit dependency → downstream test |           58.50 s |        4.58 s |     92.17% |
| Codex   | Edit → check → test → check       |           39.79 s |       29.27 s |     26.43% |
| Codex   | Check → build → check             |          206.23 s |      130.69 s |     36.63% |
| Codex   | Edit → fmt → clippy → test        |           48.69 s |       32.48 s |     33.30% |

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
| ruff    | Unchanged file                 |  115.06 ms |  114.07 ms |  1.0009 (0.8914–1.1232) |
| ruff    | Already formatted comment      |  178.10 ms |  181.84 ms |  1.1382 (0.9760–1.3434) |
| ruff    | Whitespace requiring a rewrite |  228.99 ms |  239.34 ms |  1.1170 (0.9726–1.3065) |
| uv      | Unchanged file                 |   87.03 ms |  151.70 ms |  1.3260 (1.1025–1.5923) |
| uv      | Already formatted comment      |  831.63 ms |  898.97 ms |  1.0525 (0.9948–1.1167) |
| uv      | Whitespace requiring a rewrite | 1486.13 ms | 1578.68 ms |  1.0680 (1.0370–1.1011) |

The last column gives the geometric mean of the within-pair time ratios. Values above 1 mean -11 took longer. The 99% intervals use 20,000 bootstrap resamples of the pairs. [Paired timings, fixtures, and reproduction instructions](formatting-comparison.json)

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
