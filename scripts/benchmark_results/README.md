# Published benchmarks

The current [developer-workflow](developer-workflows.json), [individual-command](workflow.json), [session](sessions.json), [historical-session](historical.json), [ablation](ablation.json), [disk](disk.json), and [ty session and worktree](ty-worktree.md) reports supply the README tables. They retain individual measurements, source identities, settings, and available evidence links.

The release benchmark reports use the published Ohm 1.99.0-6 binaries. The
[build provenance](workflow-build.json) records the release archives, source pins, and binary hashes
verified on the Mac and Linux hosts. The reports retain accepted measurements and link to raw logs,
CPU traces, source audits, and excluded attempts.

The [raw evidence](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-6-4c43f2319969)
contains command logs, source audits, CPU traces, and excluded attempts. The
[archived reports and generators](https://github.com/astral-sh/ohm/releases/tag/benchmark-comparison-evidence-1.99.0-6-218caca3c1ea)
retain the full campaign inputs and their file hashes. The checked-in reports select the stock and
default Ohm measurements and omit detailed traces. Original run settings and omitted measurements
remain in the archives.

[Raw evidence for Ohm 1.99.0-5](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-5-940c95bb89ba)
and the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts)
preserve earlier studies. Different releases may use different machines or workloads; historical
measurements are not controlled comparisons between Ohm releases.

The separate [Ruff edited-check study](ruff-edited-check.json) retains 64 matched pairs for the
unreleased [public API graph optimization](https://github.com/astral-sh/ohm-rust/pull/194). Its
[build record](ruff-edited-check-build.json) describes that experimental compiler. These results are
excluded from the release tables; that study's raw archive remains unpublished.

## Publish results

Prepare audited reports named `workflow.json`, `sessions.json`, `historical.json`, `ablation.json`, and `disk.json`, following the existing formats. Archive the ty study's evidence before replacing `ty-worktree.json` and `ty-worktree.md`. The developer workflows are measured separately: combine their three completed runs with `scripts/workflow_results.py`, archive their logs and CPU traces, and replace `developer-workflows.json` with the validated report and evidence metadata. Install formatting dependencies with `npm ci --ignore-scripts`, then run:

```console
python3 scripts/publish_benchmarks.py /path/to/audited-reports
```

The publisher checks versions, sample counts, test counts, and arithmetic. It uploads and verifies an evidence archive before replacing the five current reports and generating the README tables. It refuses to replace the current release's results. After updating a separately measured developer-workflow report, use `python3 scripts/publish_benchmarks.py --render` to refresh the tables from the checked-in reports. Review and commit the diff.

The publisher uses `gh-auto`; source and host-contention audits must be completed separately. CI checks the reports and tables without network access:

```console
python3 scripts/publish_benchmarks.py --check
```
