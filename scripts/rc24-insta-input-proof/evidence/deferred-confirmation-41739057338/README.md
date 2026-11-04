# Six fresh Cargo hardware pairs on Ruff #29604

On the first unchanged `cargo +ohm test -p ty_project --lib --no-run --locked --offline -j4 --message-format=json`, the parent used **4.1841× as many retired user instructions** as the candidate at the median of the six paired ratios. The paired range was 4.1836–4.1850×. Every measurement includes Cargo and its ordinary descendants. Measures of elapsed time and the two earlier unscored pilot pairs are outside this cohort. [Six original hardware jobs](https://github.com/astral-experiments/ohm/actions/runs/41739057338) · [Registration](https://github.com/astral-experiments/ohm/tree/c00b41f0b57a56354c8710f7e37fe69b74e2f8af/scripts/rc24-insta-input-proof)

| Fresh boot in registered order | Old Cargo instructions | Candidate instructions | Old / candidate |
|---|---:|---:|---:|
| block-1-PC | 52,999,012,580 | 12,666,884,982 | 4.1841× |
| block-2-CP | 52,983,441,423 | 12,664,384,331 | 4.1837× |
| block-3-CP | 53,002,554,201 | 12,664,983,126 | 4.1850× |
| block-4-PC | 52,995,064,242 | 12,667,425,757 | 4.1836× |
| block-5-PC | 52,996,373,603 | 12,665,522,110 | 4.1843× |
| block-6-CP | 53,006,203,006 | 12,668,391,156 | 4.1841× |

All six primary observations favored the candidate. Under independent equally likely directions on the six boots, the exact paired sign test gives one-sided p = 1/64 (0.015625) and two-sided p = 2/64 (0.03125). The predeclared orders placed each arm first three times. All four prior pilot boot IDs were excluded.

## All ordinary measured stages

The table reports medians across the six boots. The percent is the median within-boot change in instructions. Every absolute count and stage order is in `whole-command.csv`.

| Ordinary stage | Old median | Candidate median | Candidate change |
|---|---:|---:|---:|
| old | 1,809,354,995,929 | 1,809,382,838,498 | +0.002% |
| old-repeat | 52,994,931,920 | 12,667,044,530 | -76.099% |
| edit | 70,918,560,789 | 30,587,652,870 | -56.872% |
| first-unchanged | 52,997,693,091 | 12,666,203,546 | -76.100% |
| second-unchanged | 53,004,371,375 | 12,666,544,811 | -76.099% |
| check-after-test | 115,013,283,403 | 115,013,116,210 | +0.009% |
| check-unchanged | 998,018,969 | 991,827,967 | -0.630% |
| check-second-unchanged | 997,064,761 | 990,997,848 | -0.618% |
| build-after-test | 1,045,632,220,969 | 1,045,423,044,616 | -0.036% |
| build-unchanged | 461,889,721 | 460,216,075 | -0.361% |
| build-second-unchanged | 461,849,851 | 460,181,535 | -0.357% |
| empty-new | 1,809,257,040,043 | 1,809,454,752,704 | +0.016% |

The common-workflow cost guard compares the same unchanged check or build across both orderings, using thresholds of 5% and 10 million extra instructions. Its hold decision was **false**. `verified.json` records all individual guard conditions. The primary result, the immediate source edit, the cold and already-fresh checks/builds remain separately named.

## Compiler work, native verdicts and storage

The independent, unscored kernel census saw full `insta` and `ron` with the release-source parent and full `ron` with the candidate on every boot. Both launched one real `ty_project` link-only rustc and one physical stock Wild linker. The parent’s eliminated `insta` alone retired 40,325,412,923–40,339,798,639 user instructions. Its private census is excluded from the ordinary measurements. `kernel-separate.csv` gives the true executable counts by boot.

Both roles progressed from 77 to 78 real tests, including the added unrelated-file revision test. The ordinary edited ELF matched its independent empty in every installation. The 1 distinct edited ELF/list pair(s) are enumerated per boot in `native-identities.json`; representative size 182,258,808 bytes, SHA-256 `1a941001b167970f98b787bbc6e5574f46e6439bd3d030ca4d1be31f448dc185`. Each installation hit two genuine E0308s and passed the repair checks. Across all 12 installations there are 24 invalid verdicts and 144 separate ordinary hardware measurements.

The recorded scope covers the translated dependency inputs. On the six parent installations these occupied 248,440 logical bytes in 144 files. The candidate occupied 326,390 logical bytes in 144 files. Whole-target allocated space has a different scope.

Both programs are independently built, release-profile all-static Cargo from `abc70d60a6fd89c10d5f65cf85820d9b78d5affe` and `1b44b5d3dc540c491c79bbf47fae8b286e8f797a`. The published -24 Rust, SDK, Wild and source are fixed. The distribution’s PGO/BOLT Cargo has separate signed correctness controls. Candidate v6 retains the original package checksums and charges their validation specifically after a real prerequisite was rebuilt. [Optimized eleven-command migration](../deferred-pilot-41736348154/README.md) · [Signed predecessor, downgrades and pristine registry controls](../nonempty-registry-history/README.md)

## Reopen the six original ZIPs

From the packaging checkout, run

```sh
s=scripts/rc24-insta-input-proof
d=$s/evidence/deferred-confirmation-41739057338
python3 -IB "$s/price-review.py" "$d" --suite "$s" \
  --crate "$s/evidence/deferred-pilot-41736348154/insta-1.48.0.crate" \
  --prior-boots "$d/prior-boots.json"
```

The verifier checks the immutable GitHub archive digests and sizes. It parses the original Cargo and PMU records, verifies the signed SDK, both matched Cargo identities and kernel exec arguments, and reconstructs each paired result from the retained inputs. `SHA256SUMS` binds every member. The full 55-member workspace telemetry is a different preregistered follow-up.
