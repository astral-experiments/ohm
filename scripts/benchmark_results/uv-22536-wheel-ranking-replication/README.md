# Checking the uv wheel-ranking edits on two independent hosts

**12 of the 12 preselected rustc comparisons cleared a 20% instruction reduction on both hosts.** Each comparison pairs the same compiler invocation after the same real edit. Passing requires all eight pairs and both four-pair medians to clear the threshold on each machine.

For the two code edits together, median Cargo time went from 3.783 s to 2.080 s on the first host and from 3.021 s to 1.760 s on the second. The median of the paired wall-time ratios was **1.744× and 1.719×**. Whole-Cargo retired instructions fell by 48.07% and 48.07%, respectively.

The control used the signed Ohm −22 compiler. The candidate used the release-optimized rustc `ac67101cb973e35ce8ff044cc8014c2c76bab69e`. Both used the same signed Cargo and `cargo check -p uv-client --locked --offline -j8`. The first edit adds wheel variant ranking, the middle commit edits documentation and the last renames a public type. The measurements give the combined effect of the compiler changes. [Landed uv changes](https://github.com/astral-sh/uv/pull/22536) · [Compiler inventories](https://github.com/astral-experiments/ohm/blob/d321c51ee1859c63241f48280ca420c130ab2015/scripts/uv-check-22536/production-inputs.json.gz)

| Edit | First wall speedup | Second wall speedup | Pairs above 2×, first / second | Six rustcs, first cut | Six rustcs, second cut |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wheel ranking | 1.787× | 1.770× | 1/8, 0/8 | 53.23% | 53.23% |
| Documentation | 1.040× | 1.042× | 0/8, 0/8 | 4.51% | 4.55% |
| Public type rename | 1.666× | 1.668× | 0/8, 1/8 | 47.81% | 47.81% |
| Both code edits | 1.744× | 1.719× | 0/8, 0/8 | 50.65% | 50.65% |
| All three checks | 1.496× | 1.497× | 0/8, 0/8 | 41.52% | 41.53% |

## Retired instructions in each compiler

| Crate | Wheel ranking, first | Wheel ranking, second | Type rename, first | Type rename, second |
| --- | ---: | ---: | ---: | ---: |
| `uv_cache` | 48.37% | 48.38% | 40.81% | 40.81% |
| `uv_client` | 64.76% | 64.76% | 59.36% | 59.36% |
| `uv_configuration` | 47.77% | 47.76% | 40.12% | 40.12% |
| `uv_distribution_types` | 41.36% | 41.36% | 36.23% | 36.23% |
| `uv_metadata` | 38.50% | 38.50% | 43.36% | 43.36% |
| `uv_torch` | 43.44% | 43.44% | 38.37% | 38.38% |

The percentages above are one minus the reciprocal of the median paired control/candidate instruction ratio. The hardware counters include the compiler's threads and exclude child processes. Separate invocations measured inherited whole-Cargo instructions and unwrapped wall time. Across both hosts the independent reader reopened 576 compiler counter records, 96 whole-Cargo counters and 96 wall clocks. The second host reversed every pair's arm order.

The first host completed measurement before an isolated Python import failed during final replay. Its original artifact passed the separately registered offline replay. The initial second-host startup stopped before calibration. The successful retry used a fresh runner and verified that −22 was still the latest signed release before and after measurement. [First-host evidence](https://github.com/astral-experiments/ohm/tree/31158a4bad720a3d8f7cdc9613e613730033b71a/scripts/benchmark_results/uv-22536-wheel-ranking-check) · [First scored run](https://github.com/astral-experiments/ohm/actions/runs/41531636175) · [Unscored startup](https://github.com/astral-experiments/ohm/actions/runs/41562486393) · [Second scored run](https://github.com/astral-experiments/ohm/actions/runs/41564083893)

From the repository root, run the following command to reopen the second-host service original, validate every native eligibility gate and reconstruct the paired endpoints.

```sh
python3 -ISB scripts/benchmark_results/uv-22536-wheel-ranking-replication/replay.py
```

The exact ratios and sign counts for both hosts are in `two-host.json`. The source and input hashes, pair order and eligibility rule were fixed before dispatch. [Registered comparison](https://github.com/astral-experiments/ohm/blob/d321c51ee1859c63241f48280ca420c130ab2015/scripts/uv-check-22536/replication.json)
