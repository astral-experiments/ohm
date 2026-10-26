# Published benchmarks

We compared published Ohm 1.99.0-11 with stock Rust 1.99.0. Each workload ran both toolchains on the same machine. [Developer workflows](developer-workflows.json) · [Individual commands](workflow.json) · [Recorded sessions](sessions.json) · [Historical replays](historical.json) · [Ablations](ablation.json)

The published -11 compiler completed the uv recorded session, the historical Ruff replay, and both uv disk scenarios that crashed on -10. All eight APFS cohorts completed. [Disk measurements](disk.json) · [ty session and worktree startup](ty-worktree.md)

The build record identifies each suite’s host, release archive, installed binaries and workload revisions. The ty report includes individual ext4 and Btrfs measurements. [Build provenance](workflow-build.json) · [ty data](ty-worktree.json) · [Trust settings](../../BENCHMARKS.md#recorded-measurements) · [Earlier developer workflows](1.99.0-9/developer-workflows.md)

The [historical reports and fixtures](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) and [study-specific reproduction inputs](https://github.com/astral-sh/ohm/tree/444cf954135e74a52b4c9f3f6990d0bc6aff1a5a/benchmark-inputs) preserve the earlier workloads and methods. Host assignments and workloads can differ between releases.

The separate [Ruff edited-check study](ruff-edited-check.json) retains 64 matched pairs for an earlier experimental version of the [public-API metadata optimization](https://github.com/astral-sh/ohm-rust/pull/194), which is included in Ohm 1.99.0-7. Its [build record](ruff-edited-check-build.json) identifies that experimental compiler. The release tables exclude this earlier study.

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

Prepare audited reports named `workflow.json`, `sessions.json`, `historical.json`, `ablation.json`, and `disk.json`. Record the ty measurements in `ty-worktree.json` and `ty-worktree.md`. Combine the three developer-workflow runs with `scripts/workflow_results.py` and save the validated `developer-workflows.json`.

Install formatting dependencies with `npm ci --ignore-scripts` and run the publisher locally.

```console
python3 scripts/publish_benchmarks.py /path/to/audited-reports
```

The publisher checks versions, sample counts, test counts, and arithmetic before writing the reports and tables. It refuses to replace the current release's results. After updating a separately measured developer-workflow report, use `--render` to refresh the tables. CI verifies them offline with the same command you can use locally.

```console
python3 scripts/publish_benchmarks.py --check
```
