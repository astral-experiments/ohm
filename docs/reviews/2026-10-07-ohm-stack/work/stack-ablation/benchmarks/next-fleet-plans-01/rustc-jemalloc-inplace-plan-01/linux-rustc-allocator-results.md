# Linux rustc allocator: mimalloc versus jemalloc

Final recommendation: return Linux rustc to jemalloc, accepting the repeated Ruff cold-check and third-edit costs. Jemalloc improves every measured Codex state in both arm orders and reduces maximum-child RSS in every cold or edit state. Independent final root review accepted all six pairs, every raw payload and proof, and the complete current ownership release.

The comparison changes Linux rustc’s allocator through the resolved release configuration. The reduced configuration removes only `rust.mimalloc = true`; the harness patch deletes the one-line `compiler/rustc/mimalloc-v1` marker. Both native allocator implementations and vendor sources remain in the captured compiler source. These measurements establish the configured allocator choice; they do not establish a 26,000-line vendor deletion or separately validate removal of every integration path. macOS Cargo #106 is a separate comparison.

Ruff cold check rises by a paired median **2.490 s (+8.92%)**, and its third-edit check rises by **0.694 s (+6.89%)**, both pairs slower. Ruff’s first edit instead improves by 1.215 s. uv cold, second-edit and third-edit commands improve; its other states vary. All five Codex states improve in both pairs, with paired medians from 0.669 to 1.548 s faster. These are two counterbalanced pairs per project, not confidence intervals or a complete-workflow speedup.

## Every command state

Positive deltas mean jemalloc was slower. Arm medians and paired medians are calculated independently. The range is the two observed paired deltas.

| Project | State | Mimalloc median (s) | Jemalloc median (s) | Paired delta (s) | Paired range (s) | Slower pairs |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ruff | Cold check | 27.797 | 30.286 | +2.490 | +1.650 to +3.330 | 2/2 |
| ruff | Warm no-op | 0.671 | 0.445 | -0.226 | -0.335 to -0.118 | 0/2 |
| ruff | Original edit 1 | 8.348 | 7.134 | -1.215 | -1.366 to -1.063 | 0/2 |
| ruff | Original edit 2 | 9.494 | 9.497 | +0.003 | -0.386 to +0.391 | 1/2 |
| ruff | Original edit 3 | 10.095 | 10.789 | +0.694 | +0.233 to +1.155 | 2/2 |
| uv | Cold check | 51.581 | 50.214 | -1.367 | -2.656 to -0.078 | 0/2 |
| uv | Warm no-op | 0.795 | 0.678 | -0.117 | -0.269 to +0.035 | 1/2 |
| uv | Original edit 1 | 5.123 | 5.172 | +0.049 | -0.169 to +0.268 | 1/2 |
| uv | Original edit 2 | 1.813 | 1.276 | -0.537 | -0.572 to -0.501 | 0/2 |
| uv | Original edit 3 | 4.913 | 4.236 | -0.677 | -0.905 to -0.449 | 0/2 |
| codex | Cold check | 147.527 | 146.320 | -1.208 | -2.360 to -0.055 | 0/2 |
| codex | Warm no-op | 2.234 | 1.565 | -0.669 | -0.767 to -0.572 | 0/2 |
| codex | Original edit 1 | 8.931 | 7.442 | -1.489 | -1.722 to -1.256 | 0/2 |
| codex | Original edit 2 | 6.923 | 5.744 | -1.179 | -1.568 to -0.791 | 0/2 |
| codex | Original edit 3 | 7.140 | 5.592 | -1.548 | -1.640 to -1.456 | 0/2 |

## Maximum-child memory

Each cell is the command’s maximum-child RSS, not the sum or peak of all concurrent compiler/Cargo processes. Jemalloc reduces cold/edit maximum-child RSS by paired medians of **181–367 MiB**, with both orders lower in all twelve such states. Warm no-op differences are near zero and mixed.

| Project | State | Mimalloc median (MiB) | Jemalloc median (MiB) | Paired delta (MiB) | Paired range (MiB) | Higher pairs |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ruff | Cold check | 1889.56 | 1601.87 | -287.69 | -291.27 to -284.11 | 0/2 |
| ruff | Warm no-op | 61.88 | 61.88 | +0.00 | -0.00 to +0.00 | 1/2 |
| ruff | Original edit 1 | 1689.29 | 1322.73 | -366.56 | -375.16 to -357.95 | 0/2 |
| ruff | Original edit 2 | 2235.05 | 1884.51 | -350.55 | -354.56 to -346.53 | 0/2 |
| ruff | Original edit 3 | 2293.88 | 2000.19 | -293.69 | -296.18 to -291.20 | 0/2 |
| uv | Cold check | 752.19 | 532.78 | -219.41 | -223.09 to -215.73 | 0/2 |
| uv | Warm no-op | 91.48 | 91.48 | +0.01 | -0.24 to +0.25 | 1/2 |
| uv | Original edit 1 | 749.64 | 532.64 | -217.00 | -221.16 to -212.85 | 0/2 |
| uv | Original edit 2 | 500.44 | 319.26 | -181.19 | -181.19 to -181.18 | 0/2 |
| uv | Original edit 3 | 658.77 | 475.84 | -182.93 | -185.17 to -180.69 | 0/2 |
| codex | Cold check | 2013.19 | 1738.74 | -274.46 | -288.68 to -260.23 | 0/2 |
| codex | Warm no-op | 183.76 | 183.82 | +0.06 | -0.12 to +0.25 | 1/2 |
| codex | Original edit 1 | 1970.63 | 1696.66 | -273.96 | -283.49 to -264.44 | 0/2 |
| codex | Original edit 2 | 1399.84 | 1126.55 | -273.29 | -293.74 to -252.84 | 0/2 |
| codex | Original edit 3 | 1318.89 | 1058.84 | -260.04 | -266.99 to -253.09 | 0/2 |

## Scope and validation

All six pairs ran on the released 32-CPU oss7 host, two per Ruff, uv and Codex. Each arm starts independent empty target/shared-build histories and runs the original cold check, warm no-op and three original edits, with selected libraries at eight jobs. Commands preserve `--locked --offline --lib`; project tests and final executable linking are outside these timings. uv’s third edit affects test sources and may be inactive for the selected library targets.

The local and independent root audits verify all 60 successful command logs, source and lock bindings, output parity, **1,072 continuous monitor samples** and **96 required quiet samples**. It retains the original complete quiet thresholds and whole-pair rejection rules. All six pairs succeeded on their first measured attempts; the initial local API authentication failure occurred before any POST and is retained. An earlier untimed loader-path failure is preserved and repaired without repeating completed full-runtime hashing or native/build/training work.

Both current runtimes have 69,859 files, with 66,170 original shipping-core files each, separate own runtime inodes and fourteen tool-loading graphs across both environments. The prior accepted optimized build, independent own four PGO profiles and one BOLT profile per arm, source/training proofs and native validation are reused. The actual allocator configuration difference and native implementation binding were separately reviewed. Baseline 25 compiletests and three source-unit cases reuse the original accepted control; reduced validation also checks 44 linked, 15 header and two foreign histories, plus 28 stdlib and 27 rmeta cases. These focused checks do not establish universal allocator/compiler compatibility.

## Evidence

- [Final independent command, proof and ownership review](allocator-final-root-review-01.json).
- [Actual 47-proof readiness root review](allocator-actual-current-root-review-01.json).
- [Local complete command audit and all raw paired cells](allocator-complete-command-self-review-01.json).
- [Raw manifest: 633 payloads, with original tar modes](complete-raw-retrieved-ssh-01/packet/validation/allocator-complete-01/packet.json).
- [Independent local safe extraction and full rehash](complete-raw-retrieved-ssh-01/local-safe-extraction-and-rehash-01.json).
- [Final current release: all twelve recorded identities/groups, collectors/readers, task users and leases clear](final-current-release-actual-ssh-01/decoded.json).

The final review preserves all source, training, allocator and native evidence, along with every timing and memory state. This report does not sum allocator effects with other ablation candidates.
