# Four-round compiler comparison

The compact opt-in reduced retained build storage by about 14% for Ruff and 19% for uv in this controlled four-round study. Fresh-build and real-edit timing changes were generally small; Ruff’s synthetic inline edits incurred a larger cost. These measurements use fixed Cargo `4a281305` and Wild `9179eb98`. The completed [current Cargo confirmation](current-cargo-results.md) retains its separate two-round boundary; the [shipping recommendation](README.md) considers both datasets without pooling them.

`Baseline` is Rust `348339dd` before the format changes. `Off` is the narrowed Rust `3b84b46e` compiler with ordinary artifacts. `On` is that same compiler with `-Zohm-compact-artifacts=yes`; Cargo also embeds complete raw metadata for archive portability. All arms use the same Cargo and Wild binaries. A fourth historical Rust `9546795c` arm was retained in the raw data to measure the removal of research machinery; the three arms below describe the intended opt-in comparison.

There are four fresh target/build/scratch lanes per arm/project, balanced arm order, and three sequential edits in each class per round. Application edits change an observable CLI message in Ruff or uv. Library edits change Ruff’s unused-variable diagnostic in `ruff_linter` or uv’s package-name parsing diagnostic in `uv-pep508`. Synthetic inline edits change an injected function value observed at runtime. Each command is followed by exact runtime checks. Fresh means a new artifact lane, not an empty download cache or a cold operating-system cache.

## Rebuild time

The table reports arithmetic means of whole Cargo command wall time. Percentage deltas are ratios of means; positive means slower. Fresh builds have four pairs; each edit class has twelve pairs drawn from four independent rounds. Post-command census and runtime checks are outside wall timing.

| Project | Work                  | Baseline s | Off s   | On s    | On vs baseline     | Off vs baseline   | On vs off          |
| ------- | --------------------- | ---------- | ------- | ------- | ------------------ | ----------------- | ------------------ |
| Ruff    | Fresh build           | 123.534    | 123.676 | 123.581 | +0.047 s (+0.04%)  | +0.142 s (+0.11%) | -0.095 s (-0.08%)  |
| Ruff    | Application edit      | 1.694      | 1.787   | 1.825   | +0.131 s (+7.74%)  | +0.093 s (+5.47%) | +0.038 s (+2.15%)  |
| Ruff    | Library edit          | 21.247     | 21.232  | 21.519  | +0.271 s (+1.28%)  | -0.015 s (-0.07%) | +0.287 s (+1.35%)  |
| Ruff    | Synthetic inline edit | 2.671      | 2.758   | 3.093   | +0.422 s (+15.79%) | +0.086 s (+3.23%) | +0.335 s (+12.16%) |
| uv      | Fresh build           | 142.907    | 141.104 | 142.937 | +0.031 s (+0.02%)  | -1.803 s (-1.26%) | +1.833 s (+1.30%)  |
| uv      | Application edit      | 7.414      | 7.552   | 7.498   | +0.084 s (+1.13%)  | +0.138 s (+1.87%) | -0.054 s (-0.72%)  |
| uv      | Library edit          | 22.416     | 22.760  | 22.417  | +0.002 s (+0.01%)  | +0.344 s (+1.53%) | -0.342 s (-1.50%)  |
| uv      | Synthetic inline edit | 7.906      | 7.728   | 7.598   | -0.308 s (-3.89%)  | -0.178 s (-2.25%) | -0.130 s (-1.68%)  |

On Ruff, the 0.42-second synthetic cost is additional time on a 2.67-second rebuild. The existing dependency edit takes about 21 seconds and adds 0.27 seconds; the roughly 124-second fresh build is effectively unchanged versus baseline. The observed cost is much smaller relative to those longer builds and does not grow proportionally with build duration. This does not establish a constant overhead or the frequency of these edit types in real development. These absolute costs support an opt-in storage tradeoff rather than an adoption hold based only on the synthetic percentage.

### Variation

The paired-percent median and [minimum, maximum] below retain edit-to-edit variation. These are observed ranges, not confidence intervals.

| Project | Work                  | Off / baseline            | On / off                  | On / baseline             |
| ------- | --------------------- | ------------------------- | ------------------------- | ------------------------- |
| Ruff    | Fresh build           | +0.17% [-1.10%, +1.24%]   | -0.32% [-0.69%, +1.03%]   | +0.29% [-1.23%, +0.82%]   |
| Ruff    | Application edit      | +4.15% [-11.61%, +29.66%] | +4.64% [-16.60%, +22.23%] | +7.28% [-6.22%, +30.66%]  |
| Ruff    | Library edit          | -0.44% [-2.58%, +2.92%]   | +0.60% [-2.25%, +4.48%]   | +1.18% [-3.28%, +6.64%]   |
| Ruff    | Synthetic inline edit | +0.69% [-5.70%, +22.92%]  | +9.21% [-4.93%, +36.67%]  | +15.32% [+2.78%, +34.30%] |
| uv      | Fresh build           | -1.63% [-2.74%, +1.00%]   | +1.23% [+0.23%, +2.50%]   | -0.14% [-1.89%, +2.29%]   |
| uv      | Application edit      | +2.36% [-8.85%, +14.05%]  | -0.35% [-9.23%, +5.56%]   | +1.68% [-8.95%, +14.82%]  |
| uv      | Library edit          | +0.75% [-1.16%, +5.45%]   | -1.45% [-5.09%, +2.03%]   | -0.31% [-3.53%, +5.51%]   |
| uv      | Synthetic inline edit | -0.28% [-15.69%, +10.31%] | -1.06% [-8.85%, +4.24%]   | -3.07% [-15.11%, +4.60%]  |

Each entry below is the percentage change of round-mean wall time in rounds 1 / 2 / 3 / 4. Three sequential edits are averaged within their round. The two rerun uv rounds used fresh lanes under the predeclared continuation policy.

| Project | Work                  | Off / baseline rounds              | On / off rounds                     | On / baseline rounds                 |
| ------- | --------------------- | ---------------------------------- | ----------------------------------- | ------------------------------------ |
| Ruff    | Fresh build           | +0.55% / +1.24% / -0.21% / -1.10%  | -0.52% / -0.69% / +1.03% / -0.12%   | +0.03% / +0.55% / +0.82% / -1.23%    |
| Ruff    | Application edit      | +0.64% / +16.84% / -1.84% / +6.45% | +6.37% / -8.31% / +12.81% / -0.50%  | +7.06% / +7.12% / +10.73% / +5.92%   |
| Ruff    | Library edit          | +0.46% / +0.47% / -1.17% / -0.04%  | +2.45% / -0.59% / +3.53% / +0.06%   | +2.91% / -0.12% / +2.31% / +0.01%    |
| Ruff    | Synthetic inline edit | +2.67% / +7.55% / -0.22% / +2.92%  | +1.19% / +3.89% / +28.89% / +15.49% | +3.89% / +11.73% / +28.61% / +18.86% |
| uv      | Fresh build           | -1.14% / -2.12% / +1.00% / -2.74%  | +1.19% / +0.23% / +1.27% / +2.50%   | +0.03% / -1.89% / +2.29% / -0.31%    |
| uv      | Application edit      | -0.44% / +0.17% / +7.31% / +0.75%  | -1.58% / -3.51% / +1.14% / +1.15%   | -2.01% / -3.35% / +8.53% / +1.91%    |
| uv      | Library edit          | -0.03% / +1.62% / +2.30% / +2.28%  | -0.53% / -2.61% / -0.34% / -2.54%   | -0.56% / -1.03% / +1.95% / -0.32%    |
| uv      | Synthetic inline edit | -12.88% / +4.15% / +0.38% / +0.59% | +2.37% / -2.22% / -2.70% / -3.99%   | -10.82% / +1.84% / -2.33% / -3.42%   |

## Allocated build storage

Storage covers the complete post-command target/build/scratch lane, with hardlinked inodes counted once. It includes raw metadata, compact archives and incremental objects, plus ordinary caches and scratch remnants. There is no external object store. GiB/MiB use powers of two. This is retained allocated space, not peak disk or unique CoW extents; source/download caches are outside the lane.

| Project | State       | Off GiB | On GiB | Saved      | Reduction | Paired reduction range |
| ------- | ----------- | ------- | ------ | ---------- | --------- | ---------------------- |
| Ruff    | Fresh build | 2.5725  | 2.2155 | 365.66 MiB | 13.881%   | 13.879–13.882%         |
| Ruff    | Final no-op | 2.5640  | 2.2069 | 365.66 MiB | 13.927%   | 13.926–13.928%         |
| uv      | Fresh build | 3.5103  | 2.8544 | 671.62 MiB | 18.684%   | 18.683–18.686%         |
| uv      | Final no-op | 3.4326  | 2.7768 | 671.60 MiB | 19.106%   | 19.105–19.108%         |

Across all paired command states, the observed on/off storage reduction spans 13.312–13.928% for Ruff and 18.031–19.108% for uv. Off differs from baseline by only +0.0075–0.0086% Ruff and +0.0100–0.0148% uv.

## CPU and memory

CPU seconds are GNU time user plus system time across the Cargo command and children; they can exceed wall time because work runs in parallel. The last column is the on/off paired median and observed range.

| Project | Work                  | CPU baseline / off / on seconds | On / off mean change | On / off paired median [range] |
| ------- | --------------------- | ------------------------------- | -------------------- | ------------------------------ |
| Ruff    | Fresh build           | 944.597 / 939.163 / 941.325     | +0.23%               | +0.30% [-0.56%, +0.89%]        |
| Ruff    | Application edit      | 1.504 / 1.600 / 1.530           | -4.38%               | -2.89% [-25.74%, +21.57%]      |
| Ruff    | Library edit          | 94.713 / 94.304 / 94.112        | -0.20%               | -0.23% [-1.51%, +0.73%]        |
| Ruff    | Synthetic inline edit | 2.767 / 2.895 / 3.126           | +7.97%               | +3.92% [-8.03%, +32.84%]       |
| uv      | Fresh build           | 873.045 / 869.293 / 877.357     | +0.93%               | +0.98% [-0.30%, +2.05%]        |
| uv      | Application edit      | 7.774 / 7.909 / 7.623           | -3.62%               | -2.99% [-13.83%, +2.25%]       |
| uv      | Library edit          | 42.722 / 43.216 / 42.352        | -2.00%               | -2.12% [-7.00%, +2.98%]        |
| uv      | Synthetic inline edit | 8.313 / 8.145 / 7.740           | -4.97%               | -3.62% [-14.16%, +0.26%]       |

Memory uses two different measurements. Sampled tree RSS is the maximum of summed live-descendant RSS sampled every 0.5 seconds; GNU time records the maximum individual child RSS. Table cells are means of per-command peaks. Summed RSS is not PSS, can count shared mappings repeatedly and can miss short-lived peaks; largest-child RSS does not measure simultaneous total memory. The edit-phase increases below are retained as observations; their physical-memory cause is unmeasured.

| Project | Work                  | Tree RSS baseline / off / on MiB | On / off change | Child RSS baseline / off / on MiB | On / off change |
| ------- | --------------------- | -------------------------------- | --------------- | --------------------------------- | --------------- |
| Ruff    | Fresh build           | 3944.15 / 3948.54 / 3958.62      | +0.26%          | 2124.99 / 2113.25 / 2071.01       | -2.00%          |
| Ruff    | Application edit      | 268.30 / 549.66 / 816.37         | +48.52%         | 317.16 / 318.34 / 324.81          | +2.03%          |
| Ruff    | Library edit          | 1804.28 / 1816.98 / 1839.67      | +1.25%          | 1736.30 / 1754.18 / 1770.08       | +0.91%          |
| Ruff    | Synthetic inline edit | 491.71 / 489.17 / 637.65         | +30.35%         | 417.18 / 418.43 / 417.39          | -0.25%          |
| uv      | Fresh build           | 3387.32 / 3393.26 / 3316.94      | -2.25%          | 2148.15 / 2142.99 / 2136.55       | -0.30%          |
| uv      | Application edit      | 1295.21 / 1302.89 / 1397.52      | +7.26%          | 1219.96 / 1220.05 / 1222.19       | +0.18%          |
| uv      | Library edit          | 1506.67 / 1449.95 / 1562.15      | +7.74%          | 1200.41 / 1200.08 / 1203.50       | +0.29%          |
| uv      | Synthetic inline edit | 1237.60 / 1215.03 / 1500.71      | +23.51%         | 1107.82 / 1108.73 / 1108.11       | -0.06%          |

The largest observed tree-RSS sample over all phases was 3967.57 / 4003.98 / 3990.96 MiB for Ruff baseline/off/on and 3643.63 / 3500.85 / 3424.75 MiB for uv. Full per-pair memory ranges, user/system breakdowns and round data remain in the machine-readable extraction; no total-memory reduction is claimed from disk savings.

## No-op and restore commands

No-op commands invoke neither rustc nor link-only replay and retain the preceding executable hash. Their roughly one-second durations vary independently of compiler work. Restore returns the synthetic edit to its initial value and performs a real rebuild.

| Project | Work                   | Baseline / off / on seconds | On / off mean delta | On / off paired median [range] |
| ------- | ---------------------- | --------------------------- | ------------------- | ------------------------------ |
| Ruff    | First no-op            | 1.002 / 0.922 / 1.105       | +0.183 s (+19.90%)  | +15.24% [-3.24%, +53.52%]      |
| Ruff    | Final no-op            | 0.974 / 0.962 / 0.997       | +0.035 s (+3.68%)   | +4.77% [-5.63%, +11.44%]       |
| Ruff    | Restore synthetic edit | 2.618 / 2.765 / 2.799       | +0.034 s (+1.24%)   | +3.74% [-15.73%, +17.32%]      |
| uv      | First no-op            | 1.316 / 1.047 / 0.971       | -0.076 s (-7.27%)   | -3.57% [-19.21%, +0.73%]       |
| uv      | Final no-op            | 1.004 / 1.106 / 0.962       | -0.144 s (-13.04%)  | -14.23% [-21.23%, +0.57%]      |
| uv      | Restore synthetic edit | 7.522 / 7.567 / 7.667       | +0.100 s (+1.32%)   | +0.43% [-1.07%, +5.44%]        |

## Audit and scope

The independent audit verified 81,113 conditions and all 2,669 transferred files. The primary set of 416 commands consists of 312 original commands plus 104 fresh commands. All 443 raw records remain available: the prospectively excluded partial uv block contains 26 accepted commands and one outside-CPU rejection. A strict summary audit first caught floating-point cancellation in subtracting large storage means; the summarizer now takes the mathematically equivalent mean of paired differences. The original summary, failed audit and corrected summary are retained. No measurement or admission rule changed.

Scope is one Linux x86-64 host, two real projects, eight build jobs, incremental builds, line-table debuginfo and a development profile (Ruff opt-level 1 override; uv repository defaults), with explicit local native/proc-macro trust. Dependencies were prepared before measurement. The compilers are non-PGO/BOLT; this is not full optimized release performance. The unchanged resource rule rejects any unrelated compiler and three or more outside-user-CPU samples above half a core; 21 accepted primary commands retained one spike each. Four rounds do not establish statistical confidence or universal bounds, and no-op/small-edit percentages need their absolute durations.

These fixed-Cargo comparisons remain valid after the source rebase, but they are not timings of Cargo `6333daf7`: its active dependency queue changed. Rust `36f01299`’s only tip-to-tip change from the previously published cut is its Cargo gitlink; compiler sources and locked dependencies are identical. Current-Cargo functional proof and the separate 156-command confirmation must be reported at their own boundary. Earlier e55/prototype results use different source/build boundaries and should not be blended with this dataset.

Reproducible inputs: the [summary](measurements/readiness/readiness-summary.json), [independent audit](measurements/readiness/independent-primary-audit.json), and [table extraction](measurements/readiness/four-round-extraction.json). The extraction records exact source and input hashes and independently rechecks displayed means from primary raw rows. The [evaluation](readiness.md) links the portable evidence and explains the continuation; the [correctness audit](audit-correctness.md) records functional coverage separately.
