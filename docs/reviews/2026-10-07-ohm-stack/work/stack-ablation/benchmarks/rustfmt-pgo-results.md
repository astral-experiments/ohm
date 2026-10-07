# Formatter PGO: representative-command ablation

Keep the formatter portion of Rust #67. Removing only formatter PGO, with identical formatter source and unchanged compiler/Cargo/rustdoc optimization, consistently adds 0.59–2.05 seconds to first formatting and about 681 ms to Codex's dirty single-leaf edit. Warm no-op effects are small. The [separate Clippy PGO screen](clippy-pgo-results.md) also supports provisional retention.

Six counterbalanced pairs per project produced 36 independent histories and 612 ordinary commands. All source/configuration/output parity checks, all 657 monitor intervals and final ownership release passed independent and root review. No samples were dropped. Positive deltas mean PGO-OFF was slower. Paired medians are medians of pairwise differences, rather than differences of arm medians.

| Project | Command state | PGO median (ms) | PGO-OFF median (ms) | Paired delta (ms) | Paired range (ms) | Paired delta (%) | OFF slower |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ruff | first-format | 4961.5 | 6176.1 | +1224.9 | +1162.7 to +1371.7 | +24.7 | 6/6 |
| Ruff | warm-format | 188.8 | 191.5 | +3.1 | +0.5 to +7.4 | +1.7 | 6/6 |
| Ruff | warm-check | 189.3 | 191.2 | +1.0 | -0.8 to +4.1 | +0.5 | 4/6 |
| Ruff | root-format | 691.8 | 739.6 | +46.8 | +32.4 to +61.1 | +6.8 | 6/6 |
| Ruff | root-check | 189.6 | 190.6 | +2.1 | -1.6 to +3.4 | +1.1 | 4/6 |
| Ruff | leaf-format | 699.1 | 750.2 | +49.2 | +39.6 to +92.2 | +7.0 | 6/6 |
| Ruff | leaf-check | 188.5 | 191.1 | +3.8 | -0.3 to +4.1 | +2.0 | 5/6 |
| Ruff | four-file-format | 700.6 | 754.3 | +56.1 | +42.5 to +74.8 | +8.0 | 6/6 |
| Ruff | four-file-check | 190.3 | 193.3 | +2.1 | -6.0 to +6.2 | +1.1 | 4/6 |
| Ruff | four-file-clean-format | 336.5 | 343.9 | +11.9 | -1.9 to +16.4 | +3.6 | 5/6 |
| Ruff | four-file-clean-check | 187.8 | 193.4 | +4.7 | +1.6 to +6.6 | +2.5 | 6/6 |
| Ruff | four-file-fallback-format | 3341.1 | 4513.4 | +1156.7 | +1103.5 to +1251.6 | +34.6 | 6/6 |
| Ruff | four-file-fallback-check | 189.0 | 192.2 | +2.9 | +1.2 to +16.4 | +1.5 | 6/6 |
| Ruff | config-edit-format | 4985.1 | 6261.2 | +1286.0 | +1236.5 to +1354.0 | +25.6 | 6/6 |
| Ruff | config-edit-check | 189.2 | 191.5 | +2.3 | -2.3 to +11.3 | +1.2 | 5/6 |
| Ruff | config-revert-format | 5007.5 | 6273.4 | +1291.0 | +1231.6 to +1368.2 | +25.9 | 6/6 |
| Ruff | config-revert-check | 190.2 | 192.8 | +3.3 | -5.3 to +6.6 | +1.7 | 5/6 |
| uv | first-format | 2404.1 | 3006.8 | +590.2 | +345.5 to +644.8 | +24.6 | 6/6 |
| uv | warm-format | 125.9 | 125.5 | +0.2 | -34.3 to +2.9 | +0.2 | 3/6 |
| uv | warm-check | 126.4 | 125.2 | -0.7 | -16.2 to +2.0 | -0.5 | 2/6 |
| uv | root-format | 326.3 | 351.4 | +23.8 | -15.8 to +29.8 | +7.3 | 5/6 |
| uv | root-check | 125.7 | 126.2 | -0.2 | -2.4 to +1.5 | -0.2 | 3/6 |
| uv | leaf-format | 327.1 | 352.0 | +26.7 | +22.9 to +48.6 | +8.2 | 6/6 |
| uv | leaf-check | 125.5 | 124.6 | -0.7 | -5.1 to +1.0 | -0.6 | 2/6 |
| uv | four-file-format | 327.6 | 351.5 | +24.5 | +3.3 to +28.0 | +7.5 | 6/6 |
| uv | four-file-check | 124.8 | 126.3 | -0.1 | -13.5 to +4.3 | -0.1 | 3/6 |
| uv | four-file-clean-format | 188.5 | 188.2 | -0.1 | -1.0 to +3.8 | -0.1 | 3/6 |
| uv | four-file-clean-check | 126.0 | 125.3 | -0.4 | -11.9 to +10.1 | -0.4 | 2/6 |
| uv | four-file-fallback-format | 326.5 | 349.4 | +23.1 | +16.9 to +34.9 | +7.1 | 6/6 |
| uv | four-file-fallback-check | 125.1 | 126.2 | +1.1 | -11.1 to +5.4 | +0.9 | 4/6 |
| uv | config-edit-format | 2424.1 | 2988.5 | +577.0 | +474.8 to +611.6 | +23.9 | 6/6 |
| uv | config-edit-check | 125.4 | 125.4 | -0.7 | -4.9 to +0.9 | -0.6 | 1/6 |
| uv | config-revert-format | 2407.3 | 2997.7 | +592.5 | +563.7 to +615.7 | +24.6 | 6/6 |
| uv | config-revert-check | 126.9 | 125.0 | -1.3 | -6.9 to +1.6 | -1.0 | 3/6 |
| Codex | first-format | 8906.6 | 10955.4 | +2047.2 | +2002.0 to +2064.3 | +23.0 | 6/6 |
| Codex | warm-format | 312.2 | 316.6 | +4.4 | -4.2 to +7.9 | +1.4 | 5/6 |
| Codex | warm-check | 314.1 | 314.3 | +0.7 | -8.4 to +6.7 | +0.2 | 4/6 |
| Codex | root-format | 3836.4 | 4506.9 | +680.6 | +612.7 to +742.8 | +17.8 | 6/6 |
| Codex | root-check | 311.3 | 315.8 | +4.4 | -0.7 to +8.3 | +1.4 | 5/6 |
| Codex | leaf-format | 3811.0 | 4514.3 | +681.3 | +621.1 to +766.1 | +17.9 | 6/6 |
| Codex | leaf-check | 310.7 | 315.0 | +4.3 | -7.8 to +8.4 | +1.4 | 4/6 |
| Codex | four-file-format | 3823.8 | 4481.9 | +651.8 | +621.2 to +673.8 | +17.0 | 6/6 |
| Codex | four-file-check | 312.0 | 314.5 | +2.3 | -4.4 to +5.2 | +0.7 | 5/6 |
| Codex | four-file-clean-format | 2075.3 | 2385.6 | +316.1 | +285.7 to +369.2 | +15.3 | 6/6 |
| Codex | four-file-clean-check | 311.4 | 313.7 | +2.8 | -2.6 to +6.5 | +0.9 | 5/6 |
| Codex | four-file-fallback-format | 3852.2 | 4494.9 | +630.7 | +166.6 to +701.8 | +16.4 | 6/6 |
| Codex | four-file-fallback-check | 315.3 | 314.9 | +0.5 | -12.4 to +5.4 | +0.2 | 4/6 |
| Codex | config-edit-format | 9047.4 | 11033.7 | +1981.5 | +1932.6 to +2114.5 | +21.9 | 6/6 |
| Codex | config-edit-check | 311.6 | 316.1 | +4.7 | -4.4 to +11.9 | +1.5 | 5/6 |
| Codex | config-revert-format | 9036.6 | 11089.8 | +2039.4 | +1851.6 to +2104.2 | +22.4 | 6/6 |
| Codex | config-revert-check | 313.2 | 315.6 | +0.7 | -1.5 to +4.4 | +0.2 | 4/6 |

First-format removal penalties are positive in all six pairs for each project: Ruff +1,224.9 ms [1,162.7, 1,371.7], uv +590.2 ms [345.5, 644.8], Codex +2,047.2 ms [2,002.0, 2,064.3]. Dirty single-leaf edits add +49.2 / +26.7 / +681.3 ms, also all six pairs positive. The width-100 configuration edit adds +1,286.0 / +577.0 / +1,981.5 ms; it tests invalidation at the existing effective width, without measuring config-heavy fanout or a width-changing edit. These controlled command states do not estimate their frequency in a developer's day.

Command elapsed time totals 17.543 minutes. First-to-last monitoring spans 22.539 minutes. Installation, native checks, compiler builds, prefetch and rejected preparation are outside those spans; the monitoring span is not exact supervisor duration.

## Build ownership cost

The instrumented formatter build took 139.20 seconds and its training phase took 59.02 seconds in the retained build receipts. These are additional PGO phases, totalling 198.22 seconds of recorded setup. Profile-use and test phases are listed below for accounting. They ran once, without counterbalanced build order, so their differences do not establish a pipeline speedup. Each receipt includes verification/export work; RSS is maximum child RSS, not aggregate process memory.

| Arm | Phase | Elapsed (s) | User CPU (s) | System CPU (s) | Max child RSS (KiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| PGO | instrument | 139.20 | 297.45 | 42.26 | 1078968 |
| PGO | train | 59.02 | 245.70 | 60.82 | 1014348 |
| PGO | use | 145.30 | 242.14 | 52.85 | 911584 |
| PGO | test | 63.04 | 47.41 | 19.10 | 283420 |
| PGO-OFF | use | 135.18 | 232.51 | 50.58 | 912604 |
| PGO-OFF | test | 101.10 | 145.88 | 21.85 | 1023344 |

The OFF formatter/cargo-fmt export is 384,624 bytes smaller. This byte difference is separate from command latency and peak memory. The roughly three-minute extra instrumentation/training cost is material release work, but the measured first-format and Codex edit gains justify retaining formatter PGO in this stack. Keep the ordinary upstream release optimization; use the separate Clippy result to decide its extra training.

## Provenance

- Fixed same-source formatter tree: `3a2e708b…`; full runtime manifest `c34ad5dd2fad7da395125668a9dca182aab4d695b019970ba4426245a20cf771`; OFF manifest `772b9d5ea55d937143f658e1dfe3af5b1644d3cf73d69922c21199e9ec6f124b`.
- Host Direct2, boot `f4dcfa8c-16f9-466f-a366-dfe3a66d3d09`, 32 CPUs. [Accepted campaign](serc-direct2-rustfmt-pgo-off-preparation-01/accepted-campaign-retrieved-01/packet/campaigns/rustfmt-pgo-off-serc-direct2-supplementary-01/results.json), SHA-256 `51c64cbba31df604b21315fd5ab04f0a01effb7adb76a213626035afeb2b308e`.
- Archive SHA-256 `12d55d5674f6cc79d93e5f9c9e17f955eaf48231d2983659afc7fab880f657ee`; 1,972 safe regular members, including 1,971 bound payloads. The earlier incorrect readiness selector is preserved; its correction changed selector metadata only before timing.
- [Independent review](serc-direct2-rustfmt-pgo-off-preparation-01/accepted-campaign-retrieved-01/independent-campaign-review-01.json), SHA-256 `c416128dff04baf16d68ac8967afd03dbf04e49fbab686cd85568add2a437fe5`; [root recomputation](serc-direct2-rustfmt-pgo-off-preparation-01/accepted-campaign-retrieved-01/root-campaign-review.json), SHA-256 `971b8ed2185ce81581123cb5a8b9d6271c83f2adeb049eaa4551f29f801a7783`.
- Positive final release SHA-256 `d9f67df5c4be99828b0940efc6e2e38015720396763ca372fb7f2ececdf6d098`; all retained supervisor/worker groups, protected users, leases and locks released. Native 381 passes and one existing ignore were reused for the identical binaries.
- [PGO build receipts](../component-build/receipts/rustfmt-full/reviewed-overlay/receipts/README.md) and [OFF build receipts](../component-build/receipts/rustfmt-full-pgo-off/reviewed-overlay/receipts/README.md).
