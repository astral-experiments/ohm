# The edited uv check reproduced above 2× on a second worker

The repeat met its registered wall-time threshold. After applying the eight-file workspace metadata schema edit, `cargo check -p uv-client --locked --offline -j8` took 1.311 s on corrected Ohm −22 and 0.600 s on the cumulative rustc stack. The median paired speedup was **2.181×**. All eight pairs exceeded 2×. The exact one-sided sign test against 2× gives p = 0.00390625 on this worker. The two four-pair medians were 2.178× and 2.181×, and individual pairs spanned 2.152× to 2.217×. [uv edit](https://github.com/astral-sh/uv/pull/22958) · [Second run](https://github.com/astral-experiments/ohm/actions/runs/41451567448)

| Measure | First worker | Second worker | Second worker pairs above 2× |
| --- | ---: | ---: | ---: |
| Ordinary Cargo wall time | 2.151× | 2.181× | 8/8 |
| Instructions from both rustc processes | 2.588× | 2.588× | 8/8 |
| `uv_client` instructions | 3.082× | 3.082× | 8/8 |
| `uv_configuration` instructions | 1.783× | 1.783× | 0/8 |
| Whole Cargo process-tree instructions | 2.269× | 2.268× | 8/8 |

The first worker measured 2.151×. Across the two workers, 16 of 16 wall pairs exceeded 2×. Each worker supplied eight control histories and eight treatment histories, all initialized independently by Cargo. The two workers had different runner IDs and boot UUIDs. The second run excluded every one of the 19 previously registered boots. [First run](https://github.com/astral-experiments/ohm/actions/runs/41447094828) · [Plan recorded before the repeat](https://github.com/astral-experiments/ohm/blob/63e78de7f05fab8f404f0fdd7e068f80047f5c8c/scripts/benchmark_results/uv-22958-generated-impl-check/replication-plan.json)

| Pair | First worker control → stack | Speedup | Second worker control → stack | Speedup |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.378 s → 0.614 s | 2.243× | 1.309 s → 0.602 s | 2.174× |
| 2 | 1.344 s → 0.613 s | 2.190× | 1.311 s → 0.607 s | 2.159× |
| 3 | 1.338 s → 0.621 s | 2.153× | 1.314 s → 0.600 s | 2.192× |
| 4 | 1.328 s → 0.638 s | 2.080× | 1.311 s → 0.601 s | 2.183× |
| 5 | 1.314 s → 0.621 s | 2.115× | 1.291 s → 0.600 s | 2.152× |
| 6 | 1.326 s → 0.610 s | 2.173× | 1.316 s → 0.594 s | 2.217× |
| 7 | 1.316 s → 0.612 s | 2.150× | 1.314 s → 0.603 s | 2.179× |
| 8 | 1.316 s → 0.616 s | 2.134× | 1.307 s → 0.599 s | 2.183× |

The control was rustc `10d56274`, which includes the CTFE correctness fix required by this edit’s cold validation. The treatment was `ac67101c`. Both workers used the same two production-optimized SDKs, signed Cargo, checkout revisions, CPU affinity and timing code. Instructions were measured on separate visits restored from the same histories. The kernel traces cover 76 visits and 136 actual compiler executions across the two workers. [Control correction](https://github.com/astral-experiments/ohm-rust/pull/318) · [Replication harness](https://github.com/astral-experiments/ohm/tree/5182899ebd032b193efe2cf7ebf37c4c0a6e2e88/scripts/uv-client-22958)

The speedups above compare the full stack to the corrected baseline. In its separate comparison with its immediate parent, the generated-impl change reduced terminal rustc instructions by 10.05% and sped up wall time by 1.051× on uv #21041. [Marginal comparison](https://github.com/astral-experiments/ohm/tree/5e7fffae5b85b5024aac3c59d666eaec2ca8e1b3/scripts/benchmark_results/uv-21041-generated-impl-check/production-marginal)

## Reproduce the result

Run `python3 -ISB verify.py` here to recompute the eight second-worker pairs from 394 original records. Run `python3 -ISB compare-workers.py` to recompute both workers and all 16 pairs. To verify all 3,795 second-run members, download Actions artifact 13145797009 from the second run and use `python3 -ISB verify.py --original PATH/TO/ORIGINAL.zip`. Its SHA-256 is `d8bdad667a52b654d71257cf46a8161164eccf4dd0197822c26870296acdd42e`.
