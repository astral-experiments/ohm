# Published benchmarks

The current [developer-workflow](developer-workflows.json), [individual-command](workflow.json), [session](sessions.json), [historical-session](historical.json), [ablation](ablation.json), [disk](disk.json), and [ty session and worktree](ty-worktree.md) reports supply the README tables. They retain individual measurements, source identities, settings, and available evidence links.

The developer workflows use an optimized, unreleased build of Ohm 1.99.0-5 with the [retained-query cache fix](https://github.com/astral-sh/ohm-rust/pull/190), [huge-page default fix](https://github.com/astral-sh/ohm-rust/pull/191), and [Cargo validation optimization](https://github.com/astral-sh/ohm-cargo/pull/167). The checked-in report retains every accepted measurement; [build provenance](workflow-build.json) records the sources, settings, and binary hashes. Raw workflow logs, rejected attempts, compiler build recipes, and PGO/BOLT profiles are archived separately and have not been published.

[Raw logs and audits for Ohm 1.99.0-5](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-5-940c95bb89ba) include excluded attempts. Earlier reports and fixtures remain in the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts). Historical measurements are not controlled comparisons between Ohm releases.

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
