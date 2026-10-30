# Primary Ruff AArch64 library instruction counts

On the first unchanged `cargo build -p ruff_db --lib` after Ruff’s real #27849 AST bounds edit, the candidate used **10.0093× fewer whole-command userspace instructions**. Across twelve fresh balanced workers, the parent median was 2,774,567,046.5 instructions and the candidate median was 277,201,099. Every paired ratio was between 10.0059 and 10.0119. The registered third-to-tenth order-statistic interval for the median was 10.0083–10.0110× (96.14% coverage). The one-sided balanced randomization test against a sharp 2× effect gave `p = 1/924`. [Original registration](../../registered.json) · [Native-input qualification before counting](../../confirmation.md) · [Hosted run](https://github.com/astral-experiments/ohm/actions/runs/41141112097)

| Whole Cargo command | Parent median instructions | Candidate median instructions | Median paired parent/candidate | 96.14% interval |
| --- | ---: | ---: | ---: | ---: |
| Real edited library build | 7,719,309,662.5 | 5,225,162,038.5 | 1.477300× | 1.477056–1.477739× |
| First unchanged library build | 2,774,567,046.5 | 277,201,099 | 10.009265× | 10.008281–10.011047× |
| Edited build plus first unchanged | 10,493,903,359 | 5,502,361,469.5 | 1.907180× | 1.906877–1.907641× |

The command targeted `aarch64-unknown-linux-gnu` on x86-64 Linux with Ohm Rust #283 and Cargo #301. Both compilers saw the same 174 Cargo units. On an independently traced unchanged visit the parent executed one full rustc, for `portable_atomic`. The candidate executed zero rustcs and zero linkers. Both compilers rebuilt the actual Ruff edit and rejected malformed Rust with E0425. Both returned the same independently linked downstream program as an empty build. The edited downstream ELF had SHA-256 `1feb8f457dccd42626483f3b5d9f7bc29c8b147dfc199ae6ab028c83e04e0991` in all 24 private environments. The prior source produced the distinct `031fd3a90ae42a15ffcb00d536823973395bd18b2151edf5b766e43aa5ff585e`. The separate 188-unit Ruff test workflow still ran GNU ld on each unchanged visit. [Structural lib and test controls](../../README.md#structural-result) · [Actual archive readback](../library-archive-readback.json)

All 48 measured commands recorded 100% scheduled hardware counter time. The seven calibration cases covered direct, forked, grandchild, same-PID exec and one or two concurrent worker threads. The optional process-tree CPU calibration passed for 11 of the 12 pairs, so CPU-time aggregates are omitted. Wall time on the first unchanged command had a paired median ratio of 3.278× with a 3.035–4.051× interval. Hardlink-deduplicated private target plus build allocation was 566,251,520 parent bytes and 566,255,616 candidate bytes at the medians. The paired median difference was +4,096 bytes, with a range of −28,672 to +28,672 bytes. The installed compiler changes one driver by +28,592 bytes. [All endpoints, raw per-pair ratios and storage](results.json) · [Original artifact IDs and digests](manifest.json)

The separate source-built reproduction was registered before the primary result was opened. Both its qualifying conditions passed. Twelve new workers using the independent source build measured a separate first-unchanged reduction of 10.009489× (96.14% interval 10.007755–10.011816×). [Conditional replication registration](../../replication.md) · [Independent reproduction](../replication-41143416626/)

Recompute the interval and all twelve original counts offline from a checkout containing the data:

```sh
python3 -IB scripts/ohm-gnu-atomic-db/pairs.py verify scripts/ohm-gnu-atomic-db/evidence/primary-41141112097
```
