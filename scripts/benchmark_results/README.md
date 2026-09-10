# Published benchmarks

[`latest.json`](latest.json) selects the reports used for the benchmark tables. The
checked-in JSON retains timings, source identities, methodology, and audit summaries.
Each report's `evidence` field links to a checksum-verified archive containing its
original detailed report, including CPU telemetry and run-specific provenance.

The [archive through Ohm 1.98.1-2](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-1.98.1-2)
also preserves all original replay fixtures and the benchmark notes at the time of
the migration. Its manifest hashes every original file, including the removed Ruff
projections whose measurements are already in their corresponding baseline reports.
The distinct Ohm 1.97.1-18 Ruff report remains checked in.

## Publish a benchmark run

Finish the measurements and their independent audits first. Prepare a directory of
detailed reports named `workflow.json`, `sessions.json`, `historical.json`,
`ablation.json`, and `disk.json`, using the existing report formats. These are audited
publication reports, not the runners' unprocessed `results.json` files.

After `npm ci --ignore-scripts`, publish them from an Ohm checkout:

```console
python3 scripts/publish_benchmarks.py /path/to/audited-reports
```

This checks report identities, completeness, paired test counts, and arithmetic;
archives the original reports on a separate private GitHub evidence release;
downloads and verifies that archive; and writes the compact reports, `latest.json`,
and generated benchmark tables. It uses `gh-auto` and leaves the latest toolchain
release unchanged. Existing result files are never overwritten. Review and commit
the resulting diff in a benchmark PR.

The publisher preserves audit evidence; it does not perform the independent source,
workload, or host-contention audits. Historical measurements remain available and
are not controlled comparisons between Ohm releases.

CI verifies the checked-in reports and table values without network access:

```console
python3 scripts/publish_benchmarks.py --check
```
