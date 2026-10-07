# Const-impl secondary index ablation

Remove the const-impl secondary index and its dependent specialization lookup. This screen finds no representative benefit large enough to justify the extra query, index storage and solver-specific candidate enumeration. Removal improves both uv cold checks and both uv first edits; it also improves both Codex first and second edits. The cost to accept is Codex edit 3: +0.414 s (+5.86%), with both orders slower. Ruff warm no-op also becomes slower by a median 0.122 s, though one paired increase is only 0.004 s.

This recommendation covers the index from Rust #103 and only the consumer in #104 that requires it. Keep the other changes in both PRs outside this treatment. The [removal patch](../variants/rust/ordinary-const-impl-index.patch) changes five compiler files, deleting 146 lines and adding four. It removes `trait_impls_by_const_arg`, its arena-cached provider, `ConstArgImpls`, value/fallback buckets and their ordering merge, and the old solver's separate const-index iteration path. It also removes the dependent specialization candidate filter and restores the ordinary iteration route. Removing the entire PRs would exceed the measured source boundary.

The final accepted screen used one devbox, two counterbalanced pairs per project, eight jobs and the original affected-library `cargo check --locked --offline --lib` commands. Each arm started with an independent empty target/shared history and then ran a no-op and the three original recorded edits. Cargo bytes, compiler optimization policy, training recipes and public source inputs matched across arms. Original profiles were rebuilt for each source arm; this experiment reused those accepted exports and native evidence. No project test suite or final executable link was timed. The first whole Ruff attempt failed with the wrong cache path; it remains archived and contributes no sample.

All deltas below are **index removed minus index retained**. Negative values favor removal. Absolute and percentage deltas are calculated within each pair, then summarized; percentage medians therefore need not equal the ratio of the two arm medians. The range is the observed two-pair range, not a confidence interval.

| Project | State | Retained median (s) | Removed median (s) | Paired delta (s) | Paired delta (%) | Observed delta range (s) | Slower after removal |
|---|---|---:|---:|---:|---:|---:|---:|
| ruff | Cold check | 30.848 | 29.509 | -1.339 | -4.25% | -2.320 to -0.358 | 0/2 |
| ruff | Warm no-op | 0.512 | 0.634 | +0.122 | +22.35% | +0.004 to +0.240 | 2/2 |
| ruff | Edit 1 | 9.567 | 9.630 | +0.063 | +0.63% | -0.402 to +0.529 | 1/2 |
| ruff | Edit 2 | 11.750 | 11.721 | -0.029 | -0.06% | -0.682 to +0.623 | 1/2 |
| ruff | Edit 3 | 12.341 | 12.308 | -0.033 | -0.26% | -0.116 to +0.050 | 1/2 |
| uv | Cold check | 55.022 | 53.128 | -1.895 | -3.47% | -2.168 to -1.621 | 0/2 |
| uv | Warm no-op | 0.928 | 1.013 | +0.085 | +18.48% | -0.213 to +0.383 | 1/2 |
| uv | Edit 1 | 6.025 | 5.454 | -0.571 | -9.33% | -0.786 to -0.357 | 0/2 |
| uv | Edit 2 | 1.584 | 1.626 | +0.041 | +3.14% | -0.092 to +0.174 | 1/2 |
| uv | Edit 3 | 4.638 | 4.372 | -0.266 | -4.36% | -0.887 to +0.355 | 1/2 |
| codex | Cold check | 153.153 | 148.434 | -4.719 | -2.87% | -11.558 to +2.120 | 1/2 |
| codex | Warm no-op | 3.255 | 2.318 | -0.937 | -24.81% | -1.694 to -0.180 | 0/2 |
| codex | Edit 1 | 10.011 | 8.622 | -1.389 | -13.70% | -1.917 to -0.862 | 0/2 |
| codex | Edit 2 | 7.218 | 6.503 | -0.715 | -8.95% | -1.401 to -0.029 | 0/2 |
| codex | Edit 3 | 7.050 | 7.464 | +0.414 | +5.86% | +0.350 to +0.478 | 2/2 |

The cold result is consistent for Ruff (−1.339 s) and uv (−1.895 s), while Codex cold is mixed: one pair improves by 11.558 s and the other slows by 2.120 s. Ruff edits alternate direction with order and provide little evidence of a useful index effect. uv edit 1 repeatedly improves after removal by 0.357–0.786 s. Codex no-op, edit 1 and edit 2 repeatedly improve, while edit 3 repeatedly slows by 0.350–0.478 s. These separate states drive the recommendation; a history sum would hide that last regression. Warm states with small denominators can produce large percentages from small absolute changes.

The two orders remain visible below. Slot 0 ran retained→removed; slot 1 ran removed→retained. The original uv third edit is preserved even where its test-only change does not affect the selected library compilation; its timer is not evidence about test compilation.

| Project | State | Slot 0 delta (s / %) | Slot 1 delta (s / %) |
|---|---|---:|---:|
| ruff | Cold check | -2.320 / -7.30% | -0.358 / -1.20% |
| ruff | Warm no-op | +0.240 / +43.87% | +0.004 / +0.83% |
| ruff | Edit 1 | -0.402 / -4.23% | +0.529 / +5.50% |
| ruff | Edit 2 | -0.682 / -5.61% | +0.623 / +5.49% |
| ruff | Edit 3 | -0.116 / -0.93% | +0.050 / +0.41% |
| uv | Cold check | -2.168 / -4.13% | -1.621 / -2.82% |
| uv | Warm no-op | -0.213 / -18.29% | +0.383 / +55.26% |
| uv | Edit 1 | -0.786 / -12.43% | -0.357 / -6.23% |
| uv | Edit 2 | -0.092 / -5.45% | +0.174 / +11.74% |
| uv | Edit 3 | -0.887 / -17.28% | +0.355 / +8.57% |
| codex | Cold check | -11.558 / -7.20% | +2.120 / +1.45% |
| codex | Warm no-op | -0.180 / -7.14% | -1.694 / -42.48% |
| codex | Edit 1 | -1.917 / -18.47% | -0.862 / -8.94% |
| codex | Edit 2 | -1.401 / -17.46% | -0.029 / -0.45% |
| codex | Edit 3 | +0.478 / +6.70% | +0.350 / +5.02% |

Memory does not establish a substantial advantage for the index. The table shows the maximum recorded child RSS per command in MiB: the median and the observed two-pair range. It is not the sum or peak of all concurrently running compiler processes. The values largely overlap and some commands use more memory after removal, so the timing recommendation does not claim a general memory reduction.

| Project | State | Retained RSS median [range] (MiB) | Removed RSS median [range] (MiB) | Paired RSS delta median [range] (MiB) |
|---|---|---:|---:|---:|
| ruff | Cold check | 1835.5 [1833.7–1837.4] | 1873.3 [1871.6–1875.1] | +37.8 [+37.7–+37.9] |
| ruff | Warm no-op | 61.9 [61.6–62.1] | 62.0 [61.9–62.1] | +0.1 [-0.2–+0.5] |
| ruff | Edit 1 | 1673.9 [1667.6–1680.2] | 1688.0 [1684.9–1691.2] | +14.2 [+11.0–+17.4] |
| ruff | Edit 2 | 2192.5 [2186.8–2198.2] | 2183.6 [2175.7–2191.4] | -8.9 [-11.0–-6.8] |
| ruff | Edit 3 | 2242.1 [2232.0–2252.2] | 2249.9 [2235.3–2264.5] | +7.8 [+3.3–+12.3] |
| uv | Cold check | 742.1 [739.1–745.0] | 751.9 [751.7–752.1] | +9.9 [+7.1–+12.6] |
| uv | Warm no-op | 90.7 [90.6–90.9] | 90.9 [90.9–90.9] | +0.1 [-0.0–+0.2] |
| uv | Edit 1 | 750.3 [745.7–754.9] | 755.2 [742.6–767.8] | +4.9 [-12.2–+22.1] |
| uv | Edit 2 | 498.9 [493.0–504.8] | 502.1 [498.9–505.4] | +3.2 [+0.5–+5.9] |
| uv | Edit 3 | 653.8 [651.5–656.2] | 658.9 [650.9–666.8] | +5.1 [-5.3–+15.4] |
| codex | Cold check | 1995.8 [1992.6–1998.9] | 1994.1 [1990.6–1997.5] | -1.7 [-8.3–+4.9] |
| codex | Warm no-op | 182.0 [181.5–182.5] | 182.6 [182.5–182.7] | +0.6 [+0.0–+1.2] |
| codex | Edit 1 | 1956.7 [1950.3–1963.1] | 1948.1 [1943.0–1953.2] | -8.6 [-20.1–+2.9] |
| codex | Edit 2 | 1389.7 [1384.7–1394.7] | 1391.2 [1390.5–1391.9] | +1.5 [-2.8–+5.7] |
| codex | Edit 3 | 1333.4 [1332.0–1334.9] | 1319.8 [1316.4–1323.2] | -13.6 [-15.6–-11.6] |

The optimization did execute in a representative dependency: the separate uv activation capture parsed all 486 profiles and found one index-provider query plus 3,427 in-memory hits in typenum 1.20.1. The bitmaps training workload recorded one query and 2,041 hits. This is useful evidence that the comparison exercises a real path. It does not establish indexed-provider hits in the warm or edited commands, and hit counts alone are not elapsed-time gains. The original optimized variant build took 86.3 minutes to prepare; that setup duration is not an index performance result.

Focused native validation covered twelve candidate compiletest revisions and four linked compile/execute histories, with accepted baseline common validation reused. Source and lock status parity passed across all measured commands. Raw log hashes and successful statuses were verified; exact warning-text equality is not claimed. Two orders per project make this a screening result: the repeated Codex edit 3 cost should remain explicit in any removal review, and a workload that depends heavily on large const-index buckets could behave differently.

The [final independent root review](ordinary-const-oss2-two-pair-01/const-final-root-review-01.json) accepts all six pairs, 60 commands, fifteen states, 1,089 continuous-monitor samples and 96 quiet samples, with both complete 69,859-file runtime maps, loader/source/native/optimizer proofs, original archive modes and final reader ownership closure. The [per-command root review](ordinary-const-oss2-two-pair-01/const-complete-command-root-review-01.json) contains every underlying cell and RSS value. The immutable [raw archive](ordinary-const-oss2-two-pair-01/complete-raw-retrieved-ssh-01/raw.tar.gz.not-included.md) has SHA256 `34141843f82061335b6be348677bb81017830544a11ed94742fca3354fc28ee9` (105,729,973 bytes). The final root receipt has SHA256 `f5d8a7790ee35b817c95c723fd2cd29433161677e95ed3d0c4b4a08aed3b1ff4`.
