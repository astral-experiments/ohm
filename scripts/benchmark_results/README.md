# Published benchmarks

[`latest.json`](latest.json) selects the five release reports used by the benchmark publisher. The [ty session and worktree report](ty-worktree-1.99.0-3.md) supplies the additional README rows.

JSON reports contain individual measurements and configuration. Their `evidence` fields link to detailed reports. [Raw logs for Ohm 1.99.0-2](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-2-6cbbfac41159) and the [archive through Ohm 1.98.1-2](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-1.98.1-2) are also available.

## Publish results

Prepare verified reports named `workflow.json`, `sessions.json`, `historical.json`, `ablation.json`, and `disk.json`, following the existing formats. Install formatting dependencies with `npm ci --ignore-scripts`, then run:

```console
python3 scripts/publish_benchmarks.py /path/to/audited-reports
```

The publisher checks versions, sample counts, test counts, and arithmetic. It uploads and verifies an evidence archive before writing the reports and README tables. Existing results are never overwritten. Review and commit the diff.

To check the tables without publishing:

```console
python3 scripts/publish_benchmarks.py --check
```
