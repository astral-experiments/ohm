# Published benchmarks

The [developer-workflow](developer-workflows.json), [individual-command](workflow.json), [session](sessions.json), [historical-session](historical.json), [ablation](ablation.json), [disk](disk.json), and [ty session and worktree](ty-worktree.md) reports record the October 21–22, 2026 (UTC) measurements. They retain individual measurements, source identities, and settings. The ty study also has a [JSON report](ty-worktree.json).

The release benchmark reports use the published Ohm 1.99.0-7 binaries. The [build provenance](workflow-build.json) records the release archives, source pins, host assignments, and binary hashes verified on the Mac and Linux hosts.

The uv run on `charlie-oss-1` and the Ruff run on `charlie-oss-7` exceeded the host CPU limit. The two Ruff developer-workflow attempts on `charlie-serc-4` contributed no samples. The replacement runs supply the published developer timings.

The comparisons use stock Rust and Ohm with the [documented trust settings](../../BENCHMARKS.md#recorded-measurements). The ablation report records its feature overrides.

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
