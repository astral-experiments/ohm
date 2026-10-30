# Independent source-built reproduction

Twelve new paired workers reproduced the reduction on the first unchanged `cargo build -p ruff_db --lib` after Ruff #27849. The parent median was **2,774,779,967** whole-command user instructions and the candidate median was **277,193,700**. The median paired parent/candidate ratio was **10.009489×** with a 96.14% order-statistic interval of **10.007755–10.011816×**. All twelve ratios lay between 10.006223 and 10.012802. The one-sided balanced randomization test against a sharp 2× effect gave `p = 1/924`. The original cohort’s separate estimate was 10.009265× (10.008281–10.011047×). [Registration made before the primary results](../../replication.md) · [Independent hosted count](https://github.com/astral-experiments/ohm/actions/runs/41143416626) · [Original twelve-pair result](../primary-41141112097/)

| Replication command | Parent median instructions | Candidate median instructions | Median paired ratio | 96.14% interval |
| --- | ---: | ---: | ---: | ---: |
| Real edited library build | 7,718,611,653 | 5,225,397,800 | 1.476961× | 1.476788–1.477253× |
| First unchanged library build | 2,774,779,967 | 277,193,700 | 10.009489× | 10.007755–10.011816× |
| Edited build plus first unchanged | 10,493,159,530 | 5,502,614,857.5 | 1.906767× | 1.906644–1.907101× |

The replication used the 119-file parent SDK and candidate rustc driver freshly rebuilt by source qualification `41141810291`. The verifier checked the exact source-run ID, QA commit and both artifact IDs and digests in every worker. Each worker had its own private source checkout, Cargo home, target and build state for each role. All 24 runner IDs and runner names across the two cohorts are distinct. Each cohort has separate raw counters, native checks, storage data, estimates and confidence intervals. [Source reconstruction](../source-41141810291.md) · [Replication workers](workers.json) · [Two-cohort inventory](../two-cohort-inventory.json)

All 48 measured commands achieved 100% scheduled hardware counter time. The optional CPU-time calibration passed on eleven of twelve workers, so the results omit CPU-time aggregates. The first unchanged command’s wall-clock ratio was 3.309× (2.671–3.430×). The paired median difference in hardlink-deduplicated private target and build allocation was **zero bytes**, with a range of −20,480 to +24,576 bytes. Individual arm median allocations were 566,251,520 parent and 566,255,616 candidate bytes. The installed compiler driver was 28,592 bytes larger. [Complete endpoints and per-pair data](results.json)

All twelve source-built pairs rejected the invalid edit with E0425 and recovered the repaired program. The independently compiled GNU AArch64 client exercised valid and past-end public Ruff AST lookups. In both cohorts, the edited, unchanged, repaired and empty builds returned the same source-appropriate caller within the fixed measurement paths. The old client SHA-256 was `031fd3a90ae42a15ffcb00d536823973395bd18b2151edf5b766e43aa5ff585e` and the new client SHA-256 was `1feb8f457dccd42626483f3b5d9f7bc29c8b147dfc199ae6ab028c83e04e0991` across all 48 private environments. Every one of the 216 individually hashed library code objects agreed across roles and workers. The separately traced unchanged `cargo test --no-run` still invoked GNU ld; the performance figures above are for the library build. [Structural test and library witnesses](../../README.md#structural-result) · [Upstream bundled-provider limitation](https://github.com/astral-experiments/ohm/tree/85a89c96b8da4dd76c5a6f15be434c2ae3e1a689/scripts/ohm-gnu-atomic-provider/evidence/transitive-native-archive)

Recount both sets independently from the original retained clock records:

```sh
python3 -IB scripts/ohm-gnu-atomic-db/reproduction.py
```
