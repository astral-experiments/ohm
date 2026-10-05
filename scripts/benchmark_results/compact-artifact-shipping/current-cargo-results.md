# Current Cargo confirmation

The current-Cargo confirmation completed all 156 commands with passing runtime checks. The independent audit passed 28,855 checks and verified 870 transferred files. These results use actual Cargo `6333daf7`, Wild `9179eb98`, and the same frozen compiler binaries as the earlier study. They remain a separate two-round dataset; they are not pooled with the four-round Cargo `4a2813050` study and do not isolate the causal effect of changing Cargo’s scheduler.

`Baseline` is Rust `348339dd`; `Off` is the narrowed Rust `3b84b46e` compiler with ordinary artifacts; `On` is that same compiler with the actual `-Zohm-compact-artifacts=yes` option. Cargo supplies compact/fast flags and full raw metadata required for archive portability. Published Rust `36f01299` differs only in the Cargo gitlink from the previously validated compiler source; the measured driver is reused byte-for-byte rather than claimed to have been rebuilt from a new Git version string.

There are two fresh target/build/scratch lanes per project and arm. Arm order is baseline/off/on, then on/off/baseline: pair precedence is reversed, but the ordinary arm is always in the middle. Each round performs a fresh build, no-op, three sequential synthetic inline edits, restore, three application edits, three library edits, and final no-op. Application/library edits change existing observable diagnostics or output in Ruff/uv; the synthetic edit changes an injected inlined helper. All rebuilt outputs must pass exact runtime oracles. Six edit pairs represent two fresh histories, not six independent rounds.

## Rebuild time

Arithmetic mean wall times and absolute deltas follow; positive percentages mean slower. Fresh means an empty artifact lane, not cold operating-system or download caches. Wall time is the whole Cargo command, excluding post-command runtime checks and file census.

| Project | Work                  | Baseline s | Off s   | On s    | On vs baseline    | Off vs baseline   | On vs off         |
| ------- | --------------------- | ---------- | ------- | ------- | ----------------- | ----------------- | ----------------- |
| Ruff    | Fresh build           | 125.034    | 124.341 | 124.405 | -0.629 s (-0.50%) | -0.694 s (-0.55%) | +0.065 s (+0.05%) |
| Ruff    | Application edit      | 1.944      | 1.885   | 1.905   | -0.039 s (-2.00%) | -0.059 s (-3.04%) | +0.020 s (+1.07%) |
| Ruff    | Library edit          | 21.234     | 21.251  | 21.489  | +0.255 s (+1.20%) | +0.017 s (+0.08%) | +0.238 s (+1.12%) |
| Ruff    | Synthetic inline edit | 2.950      | 2.788   | 2.959   | +0.009 s (+0.31%) | -0.162 s (-5.50%) | +0.171 s (+6.14%) |
| uv      | Fresh build           | 142.558    | 144.470 | 141.990 | -0.568 s (-0.40%) | +1.912 s (+1.34%) | -2.480 s (-1.72%) |
| uv      | Application edit      | 7.232      | 7.513   | 7.657   | +0.425 s (+5.88%) | +0.282 s (+3.90%) | +0.144 s (+1.91%) |
| uv      | Library edit          | 22.988     | 22.994  | 22.913  | -0.075 s (-0.33%) | +0.006 s (+0.03%) | -0.081 s (-0.35%) |
| uv      | Synthetic inline edit | 8.036      | 8.044   | 7.570   | -0.465 s (-5.79%) | +0.008 s (+0.10%) | -0.473 s (-5.88%) |

### Variation

Paired-percent medians and [minimum, maximum] show observed variation, not confidence intervals.

| Project | Work                  | Off / baseline            | On / off                 | On / baseline             |
| ------- | --------------------- | ------------------------- | ------------------------ | ------------------------- |
| Ruff    | Fresh build           | -0.56% [-1.99%, +0.86%]   | +0.08% [-1.47%, +1.64%]  | -0.50% [-0.62%, -0.38%]   |
| Ruff    | Application edit      | -2.02% [-18.40%, +11.22%] | +2.15% [-6.91%, +6.72%]  | +1.73% [-14.10%, +8.27%]  |
| Ruff    | Library edit          | -0.94% [-2.44%, +5.90%]   | +0.99% [-0.74%, +3.24%]  | +0.60% [-1.87%, +5.12%]   |
| Ruff    | Synthetic inline edit | -5.88% [-16.58%, +9.19%]  | +7.03% [-4.17%, +16.16%] | +0.77% [-11.64%, +14.16%] |
| uv      | Fresh build           | +1.34% [+0.63%, +2.05%]   | -1.71% [-2.87%, -0.54%]  | -0.40% [-0.88%, +0.08%]   |
| uv      | Application edit      | +3.37% [+0.81%, +9.17%]   | +2.06% [-6.70%, +11.64%] | +6.18% [-0.75%, +13.33%]  |
| uv      | Library edit          | +1.39% [-4.09%, +1.93%]   | -0.72% [-1.36%, +2.64%]  | +0.41% [-5.39%, +4.62%]   |
| uv      | Synthetic inline edit | -0.12% [-9.02%, +10.05%]  | -5.74% [-13.95%, +2.26%] | -6.80% [-9.48%, -0.67%]   |

Round-mean percentage changes are shown separately as round 1 / round 2. The three sequential edits of each class are averaged inside each round.

| Project | Work                  | Off / baseline rounds | On / off rounds  | On / baseline rounds |
| ------- | --------------------- | --------------------- | ---------------- | -------------------- |
| Ruff    | Fresh build           | +0.86% / -1.99%       | -1.47% / +1.64%  | -0.62% / -0.38%      |
| Ruff    | Application edit      | -5.21% / -0.60%       | +3.70% / -1.75%  | -1.70% / -2.34%      |
| Ruff    | Library edit          | +1.09% / -0.93%       | +0.86% / +1.39%  | +1.95% / +0.45%      |
| Ruff    | Synthetic inline edit | -10.50% / -0.46%      | +13.39% / -0.43% | +1.49% / -0.88%      |
| uv      | Fresh build           | +2.05% / +0.63%       | -2.87% / -0.54%  | -0.88% / +0.08%      |
| uv      | Application edit      | +3.54% / +4.25%       | +7.68% / -3.78%  | +11.50% / +0.30%     |
| uv      | Library edit          | +1.60% / -1.51%       | +0.37% / -1.08%  | +1.98% / -2.58%      |
| uv      | Synthetic inline edit | -0.70% / +0.92%       | -5.59% / -6.18%  | -6.25% / -5.32%      |

## Allocated build storage

Storage counts settled target/build/scratch allocation after each command, deduplicating hardlinked inodes. It includes archives, incremental objects, metadata, caches and scratch remnants, with no external object store. It excludes sources/download caches; it is not peak disk use or unique CoW physical extents. GiB/MiB use powers of two.

| Project | State       | Baseline / off / on GiB  | Saved on vs off | Reduction vs baseline | Reduction vs off | Paired on/off reduction range |
| ------- | ----------- | ------------------------ | --------------- | --------------------- | ---------------- | ----------------------------- |
| Ruff    | Fresh build | 2.5723 / 2.5726 / 2.2155 | 365.68 MiB      | 13.873%               | 13.881%          | 13.881–13.882%                |
| Ruff    | Final no-op | 2.5638 / 2.5641 / 2.2069 | 365.68 MiB      | 13.920%               | 13.928%          | 13.927–13.928%                |
| uv      | Fresh build | 3.5099 / 3.5103 / 2.8544 | 671.59 MiB      | 18.674%               | 18.684%          | 18.683–18.684%                |
| uv      | Final no-op | 3.4322 / 3.4326 / 2.7767 | 671.65 MiB      | 19.097%               | 19.108%          | 19.107–19.109%                |

## CPU and memory

CPU seconds sum GNU time user and system time across the command and children. Parallel work allows CPU time to exceed wall time.

| Project | Work                  | CPU baseline / off / on s   | On / off mean change | On / off paired median [range] |
| ------- | --------------------- | --------------------------- | -------------------- | ------------------------------ |
| Ruff    | Fresh build           | 953.715 / 944.835 / 944.515 | -0.03%               | -0.03% [-0.28%, +0.22%]        |
| Ruff    | Application edit      | 1.775 / 1.692 / 1.602       | -5.32%               | -1.95% [-14.94%, +0.52%]       |
| Ruff    | Library edit          | 94.280 / 94.013 / 94.380    | +0.39%               | +0.23% [-1.03%, +2.30%]        |
| Ruff    | Synthetic inline edit | 3.088 / 2.963 / 3.035       | +2.42%               | +3.41% [-15.04%, +20.07%]      |
| uv      | Fresh build           | 876.135 / 870.340 / 873.555 | +0.37%               | +0.37% [+0.04%, +0.70%]        |
| uv      | Application edit      | 7.643 / 7.905 / 7.810       | -1.20%               | -0.70% [-10.45%, +6.96%]       |
| uv      | Library edit          | 43.917 / 43.765 / 43.245    | -1.19%               | -0.65% [-4.48%, +1.41%]        |
| uv      | Synthetic inline edit | 8.525 / 8.488 / 7.732       | -8.91%               | -6.91% [-17.83%, -3.32%]       |

Memory figures are means of per-command peaks. Sampled tree RSS sums live descendants every 0.5 seconds; GNU time records largest-child RSS. Summed RSS can count shared pages repeatedly and miss short peaks; it is not PSS. Largest-child RSS is not simultaneous total memory. The table retains the observed increases. Determining their physical-memory cause would require additional measurements such as PSS or private-page accounting; disk savings do not establish memory savings.

| Project | Work                  | Tree RSS baseline / off / on MiB | On / off change | Child RSS baseline / off / on MiB | On / off change |
| ------- | --------------------- | -------------------------------- | --------------- | --------------------------------- | --------------- |
| Ruff    | Fresh build           | 3942.07 / 3910.94 / 3914.68      | +0.10%          | 2076.62 / 2087.07 / 2050.98       | -1.73%          |
| Ruff    | Application edit      | 496.65 / 594.69 / 732.46         | +23.17%         | 317.28 / 318.27 / 324.99          | +2.11%          |
| Ruff    | Library edit          | 1819.51 / 1812.90 / 1818.54      | +0.31%          | 1753.11 / 1749.79 / 1752.56       | +0.16%          |
| Ruff    | Synthetic inline edit | 532.79 / 436.71 / 611.78         | +40.09%         | 417.75 / 419.88 / 417.80          | -0.49%          |
| uv      | Fresh build           | 3265.03 / 3531.39 / 3382.30      | -4.22%          | 2164.40 / 2144.52 / 2143.07       | -0.07%          |
| uv      | Application edit      | 1263.47 / 1277.37 / 1343.92      | +5.21%          | 1218.08 / 1220.88 / 1218.25       | -0.22%          |
| uv      | Library edit          | 1368.63 / 1426.35 / 1766.22      | +23.83%         | 1211.33 / 1198.32 / 1205.32       | +0.58%          |
| uv      | Synthetic inline edit | 1278.93 / 1252.36 / 1675.11      | +33.76%         | 1099.15 / 1103.61 / 1099.20       | -0.40%          |

## No-op and restore commands

No-op commands run no compiler or link-only replay and preserve the previous executable hash. Restore returns the synthetic helper to its starting value and does rebuild. Small-command percentages should be read beside absolute seconds.

| Project | Work                   | Baseline / off / on s | On / off mean delta | On / off paired median [range] |
| ------- | ---------------------- | --------------------- | ------------------- | ------------------------------ |
| Ruff    | First no-op            | 0.912 / 0.989 / 0.951 | -0.039 s (-3.90%)   | -3.72% [-7.99%, +0.55%]        |
| Ruff    | Final no-op            | 0.979 / 0.980 / 0.906 | -0.074 s (-7.51%)   | -6.73% [-14.02%, +0.57%]       |
| Ruff    | Restore synthetic edit | 3.052 / 2.674 / 3.114 | +0.440 s (+16.45%)  | +16.46% [+15.95%, +16.97%]     |
| uv      | First no-op            | 1.267 / 1.556 / 1.023 | -0.533 s (-34.27%)  | -26.97% [-47.85%, -6.09%]      |
| uv      | Final no-op            | 1.029 / 0.992 / 1.052 | +0.060 s (+6.06%)   | +6.24% [-4.40%, +16.88%]       |
| uv      | Restore synthetic edit | 7.493 / 7.734 / 7.446 | -0.288 s (-3.72%)   | -3.68% [-5.60%, -1.77%]        |

## Audit and scope

All 156 raw commands were admitted without selection or exclusions. The unchanged resource rule rejects any unrelated compiler and three or more outside-user-CPU intervals above half a core; 10 admitted commands contain at least one recorded interval. Their exact monitor records remain in the audit. The original collected 443-raw/416-primary evidence and protected binaries remained unchanged, with preservation receipts before and after this run. Original and copied source restoration is established separately by the source-copy and Git head/diff/index checks.

Scope remains one Linux x86-64 host, two projects, incremental development builds, eight jobs, line-table debuginfo, Ruff opt-level 1 override and uv repository defaults. Local proc-macro/native trust is explicit. Compiler binaries are non-PGO/BOLT. Two rounds are a confirmation of current integration, not a statistical guarantee, a universal performance bound, or a representative distribution of everyday commands. The absolute times do not establish a constant overhead independent of project/edit shape.

The exact current-Cargo installed smoke separately passed default/compact executable, library and proc-macro checks, all four removed-option diagnostics, source/gitlink checks and original-artifact preservation. Current compiler metadata/export/lifecycle/worktree/alignment and macOS proof retain their recorded source/binary boundaries. Source-App credentials still prevent Rust GitHub CI from reaching downstream checks; no credential setup or complete optimized release is claimed.

Reproducible inputs are the [summary](measurements/current-cargo/summary.json), [independent audit](measurements/current-cargo/audit.json), and [table extraction](measurements/current-cargo/extraction.json). The extraction records full source pins and hashes and independently recomputes all 42 groups and two-round metrics from raw rows before rendering this page. The [evaluation](readiness.md) links the complete evidence and portable reproduction instructions.
