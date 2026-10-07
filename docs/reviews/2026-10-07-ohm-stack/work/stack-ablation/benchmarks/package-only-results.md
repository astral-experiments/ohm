# Package-only formatter: accepted representative-command results

The broad package-only removal changes eight files, +92/-2,237. It removes leaf certificates, topology, speculative formatting and config-fingerprint reuse while preserving package caching, buffered snapshots and one-pass verification. Full and removal use their own matched shipping-profile formatter binaries and the same Cargo/compiler/source/recipe outside the declared removal. Native correctness evidence is reused; timing executes no project tests.

All 36 histories (six counterbalanced pairs per project), 612 commands and eighteen parity pairs passed independent and root acceptance. All 645 host-monitor samples passed; process groups, protected users and leases were released. The earlier rejected preflight had no timed commands and remains preserved and excluded. Every estimate below uses the original six pairs with no outlier removal. Positive deltas mean package-only is slower. Median paired deltas need not equal the difference between arm medians.

The seventeen phases are the original recorded history: first format, warm format/check, dirty root format/check, dirty leaf format/check, dirty four-file format/check, four already-formatted leaf edits, fallback edits and config edit/revert. Each check immediately follows its corresponding format. The config history preserves effective width 100; it does not establish config-heavy fanout or width-changing edits. Source/output/configuration proofs match for every pair.

## Ruff

| Command state | Full median | Package-only median | Median paired delta | Paired range | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| first-format | 4,941.05 ms | 5,639.53 ms | +682.59 ms | +645.43 to +1,176.03 ms | 6 / 6 |
| warm-format | 190.06 ms | 266.94 ms | +78.15 ms | +69.61 to +94.61 ms | 6 / 6 |
| warm-check | 188.87 ms | 266.56 ms | +76.62 ms | +73.34 to +82.87 ms | 6 / 6 |
| root-format | 688.21 ms | 932.10 ms | +247.05 ms | +230.75 to +267.36 ms | 6 / 6 |
| root-check | 188.98 ms | 263.92 ms | +73.94 ms | -15.03 to +77.32 ms | 5 / 6 |
| leaf-format | 697.38 ms | 926.71 ms | +220.99 ms | +186.43 to +254.27 ms | 6 / 6 |
| leaf-check | 187.19 ms | 264.97 ms | +78.34 ms | +71.67 to +81.80 ms | 6 / 6 |
| four-file-format | 699.41 ms | 931.83 ms | +228.79 ms | +218.04 to +237.47 ms | 6 / 6 |
| four-file-check | 189.19 ms | 262.55 ms | +74.07 ms | +71.59 to +80.51 ms | 6 / 6 |
| four-file-clean-format | 337.95 ms | 597.32 ms | +259.14 ms | +254.57 to +275.33 ms | 6 / 6 |
| four-file-clean-check | 188.44 ms | 263.18 ms | +74.38 ms | +61.11 to +78.89 ms | 6 / 6 |
| four-file-fallback-format | 3,334.13 ms | 3,644.21 ms | +301.80 ms | -315.33 to +328.08 ms | 5 / 6 |
| four-file-fallback-check | 189.13 ms | 267.97 ms | +75.20 ms | +60.08 to +211.31 ms | 6 / 6 |
| config-edit-format | 5,047.09 ms | 5,704.46 ms | +691.67 ms | +598.15 to +850.99 ms | 6 / 6 |
| config-edit-check | 191.07 ms | 265.64 ms | +75.89 ms | +72.76 to +125.26 ms | 6 / 6 |
| config-revert-format | 4,987.08 ms | 5,736.59 ms | +756.78 ms | +692.85 to +789.27 ms | 6 / 6 |
| config-revert-check | 190.30 ms | 264.86 ms | +74.34 ms | +68.11 to +85.10 ms | 6 / 6 |

## uv

| Command state | Full median | Package-only median | Median paired delta | Paired range | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| first-format | 2,403.34 ms | 2,591.82 ms | +169.52 ms | -81.03 to +213.31 ms | 5 / 6 |
| warm-format | 125.77 ms | 147.36 ms | +21.26 ms | -29.69 to +23.65 ms | 5 / 6 |
| warm-check | 125.16 ms | 147.75 ms | +22.55 ms | +12.28 to +23.96 ms | 6 / 6 |
| root-format | 328.76 ms | 408.60 ms | +78.75 ms | +60.52 to +85.43 ms | 6 / 6 |
| root-check | 124.78 ms | 148.58 ms | +23.64 ms | +15.93 to +26.73 ms | 6 / 6 |
| leaf-format | 331.34 ms | 408.20 ms | +76.33 ms | +62.97 to +87.43 ms | 6 / 6 |
| leaf-check | 124.84 ms | 148.16 ms | +22.77 ms | +20.53 to +29.12 ms | 6 / 6 |
| four-file-format | 328.55 ms | 406.31 ms | +78.88 ms | +55.51 to +80.35 ms | 6 / 6 |
| four-file-check | 126.27 ms | 147.83 ms | +21.14 ms | +14.03 to +24.53 ms | 6 / 6 |
| four-file-clean-format | 187.33 ms | 277.95 ms | +90.49 ms | +80.06 to +93.81 ms | 6 / 6 |
| four-file-clean-check | 124.30 ms | 148.11 ms | +23.54 ms | +20.42 to +26.60 ms | 6 / 6 |
| four-file-fallback-format | 326.34 ms | 407.29 ms | +80.45 ms | +78.60 to +84.63 ms | 6 / 6 |
| four-file-fallback-check | 125.38 ms | 147.11 ms | +21.81 ms | +17.59 to +25.57 ms | 6 / 6 |
| config-edit-format | 2,396.93 ms | 2,605.18 ms | +203.41 ms | +143.02 to +263.08 ms | 6 / 6 |
| config-edit-check | 125.07 ms | 147.70 ms | +22.95 ms | +17.23 to +24.68 ms | 6 / 6 |
| config-revert-format | 2,399.84 ms | 2,612.13 ms | +211.05 ms | +155.07 to +259.86 ms | 6 / 6 |
| config-revert-check | 125.13 ms | 148.69 ms | +22.66 ms | +19.59 to +25.69 ms | 6 / 6 |

## Codex

| Command state | Full median | Package-only median | Median paired delta | Paired range | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| first-format | 8,942.93 ms | 9,862.52 ms | +943.46 ms | +782.71 to +1,065.64 ms | 6 / 6 |
| warm-format | 312.61 ms | 421.38 ms | +109.15 ms | +104.01 to +123.36 ms | 6 / 6 |
| warm-check | 311.32 ms | 418.93 ms | +107.92 ms | +105.62 to +110.61 ms | 6 / 6 |
| root-format | 3,858.53 ms | 4,418.76 ms | +560.23 ms | +83.85 to +647.37 ms | 6 / 6 |
| root-check | 314.11 ms | 419.89 ms | +104.43 ms | +67.62 to +124.08 ms | 6 / 6 |
| leaf-format | 3,846.49 ms | 4,422.80 ms | +563.85 ms | +145.26 to +1,045.30 ms | 6 / 6 |
| leaf-check | 318.29 ms | 418.54 ms | +98.68 ms | +90.83 to +136.45 ms | 6 / 6 |
| four-file-format | 3,837.24 ms | 4,750.18 ms | +909.95 ms | +535.56 to +1,054.95 ms | 6 / 6 |
| four-file-check | 311.67 ms | 435.70 ms | +111.27 ms | -40.00 to +177.10 ms | 5 / 6 |
| four-file-clean-format | 2,078.98 ms | 2,427.33 ms | +354.82 ms | +307.04 to +424.88 ms | 6 / 6 |
| four-file-clean-check | 312.40 ms | 421.20 ms | +110.44 ms | +103.50 to +119.40 ms | 6 / 6 |
| four-file-fallback-format | 3,909.58 ms | 4,412.92 ms | +583.98 ms | +154.09 to +749.26 ms | 6 / 6 |
| four-file-fallback-check | 313.34 ms | 429.55 ms | +106.35 ms | +11.44 to +178.94 ms | 6 / 6 |
| config-edit-format | 9,012.35 ms | 10,037.02 ms | +1,013.74 ms | +795.69 to +1,076.71 ms | 6 / 6 |
| config-edit-check | 313.75 ms | 419.23 ms | +104.35 ms | -132.30 to +112.76 ms | 5 / 6 |
| config-revert-format | 9,050.30 ms | 10,053.76 ms | +1,014.19 ms | +659.34 to +1,082.32 ms | 6 / 6 |
| config-revert-check | 316.38 ms | 420.95 ms | +104.56 ms | +84.30 to +112.60 ms | 6 / 6 |

## Decision and measurement limits

Hold the broad replacement as it stands; prefer narrower #18/#19 removals and retain a simpler single-leaf path provisionally. The 2,145-line reduction matters, but the measured edit costs also matter. This broad comparison does not isolate #14 or establish which individual remaining layer deserves retention. Do not add its effects to isolated #18/#19 results. Final combined-stack validation remains pending.

The ordinary commands total 17.23 minutes. First-to-last monitor samples span 22.24 minutes; that excludes setup and is not exact supervisor duration. Maximum child RSS is not aggregate memory, and endpoint disk allocation is not peak disk use. These are formatting commands, not whole development sessions or a claim about edit frequency.

## Provenance

- [Root acceptance and all recomputed statistics](serc-direct2-package-migration-01/package-accepted-attempt02-retrieved-01/root-campaign-review.json), SHA256 `e4aa6b9b9a4cfc2f568fa4bec96256ffccd73b78404aeb00d3246c9200d7055d`.
- [Independent acceptance](serc-direct2-package-migration-01/package-accepted-attempt02-retrieved-01/independent-campaign-review-01.json), SHA256 `953f74dafc7feeb7ba1fbacdda70d15902702ba8b0cb8a9b3c790508c7c58d10`.
- [Raw evidence archive](serc-direct2-package-migration-01/package-accepted-attempt02-retrieved-01/accepted-campaign.tar.gz.not-included.md), SHA256 `cd089364339a837042972f47e12fbdae9751402c21bcba0b4c55720897502a86`.
- [Coherent removal patch](../rustfmt/package-only.patch), SHA256 `39c2e84d01a91e3ffa7e7310d463acf199095bf7caf7167193784e035af8c3da`.

Root and independent reviews preserve source/native/runtime/recipe bindings, stdout/stderr/source/output/configuration parity, each timed process, monitor intervals and positive release. Raw archive member modes match the remote manifest; local extraction umask differences are recorded separately and do not describe the timing filesystem.
