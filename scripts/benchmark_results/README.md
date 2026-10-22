# Published benchmarks

On October 22, 2026, we measured published Ohm 1.99.0-8 against stock Rust 1.99.0. The reports include individual timings, source revisions, toolchain settings, and exclusion summaries. [Developer workflows](developer-workflows.json) · [Individual commands](workflow.json) · [Sessions](sessions.json) · [Historical replays](historical.json) · [Ablations](ablation.json) · [Disk usage](disk.json) · [ty session and worktree startup](ty-worktree.md)

The ty study includes the per-run measurements for ext4 and Btrfs. The build record identifies the release archives, component pins, host assignments and installed binary hashes. [ty data](ty-worktree.json) · [Build provenance](workflow-build.json) · [Trust settings](../../BENCHMARKS.md#recorded-measurements)

The formatter study compares published Ohm 1.99.0-7 and 1.99.0-8 on Ruff and uv. Each case has 40 matched pairs with warmed, persistent per-release formatter caches. [Formatter results](formatting-comparison.md) · [Formatter data](formatting-comparison.json)

The Codex developer run exhausted its retries under CPU contention, including an overlapping compiler. The report uses 40 accepted samples from its replacement run.

The [historical reports and fixtures](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) and [study-specific reproduction inputs](https://github.com/astral-sh/ohm/tree/444cf954135e74a52b4c9f3f6990d0bc6aff1a5a/benchmark-inputs) preserve the earlier workloads and methods. Host assignments and workloads can differ between releases.

The separate [Ruff edited-check study](ruff-edited-check.json) retains 64 matched pairs for an earlier experimental version of the [public-API metadata optimization](https://github.com/astral-sh/ohm-rust/pull/194), which is included in Ohm 1.99.0-7. Its [build record](ruff-edited-check-build.json) identifies that experimental compiler. The release tables exclude this earlier study.

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
