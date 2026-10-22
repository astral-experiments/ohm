# Published benchmarks

The [developer-workflow](developer-workflows.json), [individual-command](workflow.json), [session](sessions.json), [historical-session](historical.json), [ablation](ablation.json), [disk](disk.json), and [ty session and worktree](ty-worktree.md) reports record the October 21–22, 2026 (UTC) measurements. They retain individual measurements, source identities, settings, and evidence links. The ty study also has a [JSON report](ty-worktree.json).

The release benchmark reports use the published Ohm 1.99.0-7 binaries. The [build provenance](workflow-build.json) records the release archives, source pins, host assignments, and binary hashes verified on the Mac and Linux hosts.

The [raw evidence](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d) and [ty evidence](https://github.com/astral-sh/ohm/releases/tag/benchmark-evidence-ty-29327-1.99.0-7-e2a2b69a25e7) contain command logs, source audits, CPU traces, and excluded attempts. The [archived reports and generators](https://github.com/astral-sh/ohm/releases/tag/benchmark-report-inputs-1.99.0-7-f5f433e73751) retain the full campaign inputs, validation receipts, and file hashes. Checked-in reports retain accepted timings and omit detailed traces. The main comparisons use stock Rust and Ohm with the [documented trust settings](../../BENCHMARKS.md#recorded-measurements); the ablation report records its explicit feature overrides.

Each archive below has a verified SHA-256 checksum. Ruff's session archive also retains both rejected developer suites from `charlie-serc-4`; those samples are excluded from the results.

| Archive                                                                                                                                                                       | Host                      | SHA-256                                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------ |
| [uv](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-uv-1.99.0-7-raw.zip)                                               | charlie-serc-1            | `365c4c0a28d33aec8be0a04a2b9da914e78e3bf2c0fd1ca8db7946479b519fe8` |
| [Codex](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-codex-1.99.0-7-raw.zip)                                         | charlie-oss-3             | `f71c8dedb573e29ee8a5d3585294f9701d06816d52e4e8abbfbb2ceabc48b4ad` |
| [Ruff session and historical replays](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-ruff-sessions-1.99.0-7-raw.zip)   | charlie-serc-4            | `c501ffb0f05a89d82038a76691d31fd4dbffc732cbfc3467bf006ccd1610681a` |
| [Ruff developer workflows](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-ruff-developer-1.99.0-7-raw.zip)             | charlie-ohm-session-bench | `4e77d0109e3d8fd9579c56cca249c6f063d8b26464402ea6c23439b77d638b45` |
| [APFS disk usage](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/apfs-1.99.0-7-raw.zip)                                      | macOS APFS                | `7ff2148af0cf04c6648edae2e10b1374e76d43e41628f91f4f100dd4062951f2` |
| [uv rejected attempt](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-uv-excluded-charlie-oss-1-1.99.0-7-raw.zip)       | charlie-oss-1             | `bfce37511b388068c534d7b1ed6b8438f46b772f20f6ccbdc9507b77217d65ed` |
| [Ruff rejected attempt](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d/linux-ruff-excluded-charlie-oss-7-1.99.0-7-raw.zip)   | charlie-oss-7             | `e39a201d72c27ef205cf8741d6a1b3cc2fde6c55b2a76901ea6ebc585d932a2c` |
| [ty sessions and worktrees](https://github.com/astral-sh/ohm/releases/download/benchmark-evidence-ty-29327-1.99.0-7-e2a2b69a25e7/ty-29327-evidence.zip)                       | charlie-ohm-session-bench | `e2a2b69a25e740b5a7728a410f5c1e21dacbfc5b5808d63b00d64eb459bd73e1` |
| [Full reports and reproduction inputs](https://github.com/astral-sh/ohm/releases/download/benchmark-report-inputs-1.99.0-7-f5f433e73751/benchmark-report-inputs-1.99.0-7.zip) | All hosts                 | `dff13ad2ee6158296bd6f0accd1233c63424200f63d1d02ad0815c5d3e14d16c` |

Raw evidence for [Ohm 1.99.0-6](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-6-4c43f2319969) and [Ohm 1.99.0-5](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-5-940c95bb89ba), the [release 6 reports and generators](https://github.com/astral-sh/ohm/releases/tag/benchmark-comparison-evidence-1.99.0-6-218caca3c1ea), and the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) preserve earlier studies. Different releases may use different machines or workloads; historical measurements are not controlled comparisons between Ohm releases.

The separate [Ruff edited-check study](ruff-edited-check.json) retains 64 matched pairs for an earlier experimental version of the [public-API metadata optimization](https://github.com/astral-sh/ohm-rust/pull/194), which is included in Ohm 1.99.0-7. Its [build record](ruff-edited-check-build.json) identifies that experimental compiler. These earlier results remain separate from the release tables; that study's raw archive remains unpublished.

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
