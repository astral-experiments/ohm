# Published benchmarks

On October 22, 2026, we measured published Ohm 1.99.0-8 against stock Rust 1.99.0. The reports include individual timings, source revisions, toolchain settings and links to the underlying measurements. [Developer workflows](developer-workflows.json) · [Individual commands](workflow.json) · [Sessions](sessions.json) · [Historical replays](historical.json) · [Ablations](ablation.json) · [Disk usage](disk.json) · [ty session and worktree startup](ty-worktree.md)

The ty study includes the per-run measurements for ext4 and Btrfs. The build record identifies the release archives, component pins, host assignments and installed binary hashes. [ty data](ty-worktree.json) · [Build provenance](workflow-build.json) · [Trust settings](../../BENCHMARKS.md#recorded-measurements)

The formatter study compares published Ohm 1.99.0-7 and 1.99.0-8 on Ruff and uv. Each case has 40 matched pairs with warmed, persistent per-release formatter caches. [Formatter results](formatting-comparison.md) · [Formatter data](formatting-comparison.json)

The archives contain the raw commands, samples, source checks, CPU traces and excluded attempts. The Codex archive retains its rejected developer run. The developer report uses the 40 accepted samples from the replacement run.

| Archive                                                                                                                                                                       | Host                      | SHA-256                                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------ |
| [uv](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-8-05f45c638805/linux-uv-1.99.0-8-raw.zip)                                               | charlie-serc-1            | `e493f10f1b17448982d0f731b0a3dfd5e249c288ef94d1c5af7f3d4ba3c599e4` |
| [Codex](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-8-05f45c638805/linux-codex-1.99.0-8-raw.zip)                                         | charlie-oss-3             | `f11c0f7c7a0c4be7fd9e8c2464a9bc01e2b05c10d66c60fbd99193e251d34e40` |
| [Ruff](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-8-05f45c638805/linux-ruff-1.99.0-8-raw.zip)                                           | charlie-ohm-session-bench | `6759271099718d0fbc8a93042efca5d8b2ba005f70131f2eb70d7445d290ee9c` |
| [APFS disk usage](https://github.com/astral-sh/ohm/releases/download/benchmark-raw-evidence-1.99.0-8-05f45c638805/apfs-1.99.0-8-raw.zip)                                      | macOS APFS                | `b035d3e4ca15787130d1736f9c5d87882908404aee6eae43ff8062d39ccf6666` |
| [ty sessions and worktrees](https://github.com/astral-sh/ohm/releases/download/benchmark-evidence-ty-29327-1.99.0-8-3dd5a5d42175/ty-29327-evidence.zip)                       | charlie-ohm-session-bench | `3dd5a5d42175e66273b7f81d4ffb3049e933b275531b48a4b0ab8c78d39efeb6` |
| [Paired formatter comparison](https://github.com/astral-sh/ohm/releases/download/benchmark-formatting-evidence-1.99.0-8-78e3cce2d2a5/formatting-comparison-1.99.0-8-raw.zip)  | charlie-serc-1            | `afa719439f5e29fd1b5ce8f3df3cc85db2bc4a9cc1c7aadf69c713807622b7e4` |
| [Full reports and reproduction inputs](https://github.com/astral-sh/ohm/releases/download/benchmark-report-inputs-1.99.0-8-23d213697c44/benchmark-report-inputs-1.99.0-8.zip) | All hosts                 | `04e1eb91ed39ddc5a97b899e05d6c1d4deff2497f5abdc4d58a557480951cf9c` |

Raw evidence for [Ohm 1.99.0-7](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-7-2be7fb68ff9d), [Ohm 1.99.0-6](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-6-4c43f2319969) and [Ohm 1.99.0-5](https://github.com/astral-sh/ohm/releases/tag/benchmark-raw-evidence-1.99.0-5-940c95bb89ba), the [release 7 reports and generators](https://github.com/astral-sh/ohm/releases/tag/benchmark-report-inputs-1.99.0-7-f5f433e73751), the [release 6 reports and generators](https://github.com/astral-sh/ohm/releases/tag/benchmark-comparison-evidence-1.99.0-6-218caca3c1ea), and the [benchmark history](https://github.com/astral-sh/ohm/tree/9cbebcf02df6036feaea17cf16173c01185c856e/scripts) preserve earlier studies. Different releases may use different machines or workloads; historical measurements are not controlled comparisons between Ohm releases.

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
