Recommend removing parallel query promotion from compiler #66, while preserving the cache identity checks required for correctness. The six accepted pairs per project show small, mixed changes in representative development commands. Every command’s observed paired range includes both a speedup and a slowdown. This evidence does not establish a consistent gain large enough to justify the added parallel machinery.

The comparison used the frozen full Ohm toolchain and an otherwise identical toolchain with serial promotion, on one 32-CPU Linux devbox. Each arm ran five selected-library `cargo check` commands at eight jobs: cold, warm no-op, and checks after the three original source edits. Ruff, uv, and Codex each have six complete pairs, alternating full/reduced and reduced/full order. These are ordinary development commands, not test suites. The uv comparison retains the original compatibility setup and selected-library scope; it does not measure every crate affected by an edit.

Positive deltas mean the serial ablation was slower. The delta is the median of six within-pair differences; it is not the difference between the two arm medians. Ranges below contain all six within-pair differences and are observed ranges, not confidence intervals.

| Project | Command | Full median (s) | Serial median (s) | Paired median delta (ms) | Paired median delta (%) | Paired range (ms) | Serial slower |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ruff | Cold | 32.229 | 31.057 | -743.7 | -2.31% | -2693.3 to +1664.5 | 2/6 |
| ruff | Warm no-op | 1.016 | 1.063 | +42.9 | +4.06% | -179.7 to +531.7 | 5/6 |
| ruff | Edit 1 | 9.001 | 9.212 | +208.1 | +2.37% | -853.8 to +920.3 | 3/6 |
| ruff | Edit 2 | 10.961 | 11.160 | +84.4 | +0.77% | -606.7 to +690.9 | 4/6 |
| ruff | Edit 3 | 11.856 | 12.114 | +186.4 | +1.57% | -1017.3 to +899.8 | 4/6 |
| uv | Cold | 54.630 | 53.526 | -616.5 | -1.10% | -2665.6 to +1632.8 | 3/6 |
| uv | Warm no-op | 1.484 | 1.404 | -205.3 | -12.21% | -507.0 to +574.8 | 2/6 |
| uv | Edit 1 | 6.129 | 6.197 | +56.4 | +0.92% | -682.6 to +934.1 | 3/6 |
| uv | Edit 2 | 2.230 | 2.281 | -12.2 | -0.56% | -199.1 to +628.4 | 2/6 |
| uv | Edit 3 | 6.323 | 6.069 | -73.0 | -1.04% | -1188.8 to +1039.6 | 3/6 |
| codex | Cold | 154.821 | 156.022 | +342.3 | +0.22% | -2563.7 to +1931.4 | 4/6 |
| codex | Warm no-op | 3.512 | 3.435 | -7.5 | -0.23% | -419.7 to +241.1 | 3/6 |
| codex | Edit 1 | 10.757 | 10.735 | -94.0 | -0.87% | -766.3 to +1302.6 | 2/6 |
| codex | Edit 2 | 8.188 | 8.646 | +380.0 | +4.59% | -896.0 to +2354.8 | 4/6 |
| codex | Edit 3 | 8.148 | 8.048 | -131.7 | -1.58% | -720.5 to +1370.8 | 2/6 |

The largest warm/edit median cost was Codex edit 2: +379.96 ms (+4.60%), with serial slower in four of six pairs and a range from −895.96 to +2,354.85 ms. Ruff’s warm no-op was slower in five of six pairs, but its median cost was only 42.95 ms. Cold checks also varied in both directions. These results support a simplification decision; they do not prove that serial promotion is always equally fast or faster. Library codegen/build performance remains a separate ablation.

All 18 accepted pairs contain 180 timed commands. Seven whole rejected attempts remain excluded and preserved, with their ownership releases; no partial pair was reused. The final packet retains all 25 attempts and 1,928 original payloads. An independent local audit rehashed every payload, verified every attempt’s positive closure, recomputed all 15 command statistics, and checked exact agreement with the root reviewer’s independently calculated statistics. Source, lockfile, command, diagnostic, and output checks passed within the frozen selected-workload scope. The root review checked 3,404 continuous-monitor samples and 288 required quiet samples.

The later Codex attempts used a declared prospective amendment that waited for a complete quiet window after initial/prepared admission and cleanup. It changed bounded waiting only; timed commands, runtime bytes, thresholds, and continuous-monitor rules stayed fixed. Historical accepted and rejected receipts remain intact.

Evidence: [full raw packet](accepted-campaign-retrieved-03/packet/validation/serial-complete-02/packet.json), [independent audit and all raw paired deltas](independent-serial-complete-audit-01.json), [root statistics](independent-complete-results-review.json), and [final root acceptance](serial-complete-root-review.json).
