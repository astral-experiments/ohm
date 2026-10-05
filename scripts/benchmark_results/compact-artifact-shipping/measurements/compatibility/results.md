# Compatibility confirmation

All 90 commands passed receipt verification. Every arm uses the same new compiler, Cargo and Wild; this dataset is separate from earlier measurements. Two fresh forward/reverse rounds provide two clean-build observations and six sequential observations per edit class, project and arm. Ruff defaults remain in the middle position.

“Off” explicitly disables compact artifacts. “Default” uses automatic compact storage and direct Wild reading. Ruff’s “adapter” supplies the same Wild driver arguments as user configuration, so rustc materializes ordinary linker inputs. That configuration also changes Cargo cache admission; its cost does not isolate decompression.

| Project | Phase | Comparison | Reference mean (s) | Candidate mean (s) | Δ (s) | Δ (%) | Paired Δ median [range] (s) | Paired % median [range] |
|---|---|---|---:|---:|---:|---:|---|---|
| ruff | Fresh build | default vs off | 124.587 | 125.895 | +1.308 | +1.05 | +1.308 [-0.514, +3.129] | +1.05 [-0.41, +2.51] |
| ruff | Application edit | default vs off | 1.809 | 1.933 | +0.125 | +6.88 | +0.118 [-0.022, +0.302] | +6.82 [-1.11, +15.63] |
| ruff | Library edit | default vs off | 21.533 | 21.721 | +0.188 | +0.87 | +0.369 [-0.550, +0.634] | +1.73 [-2.48, +3.02] |
| ruff | Fresh build | adapter vs default | 125.895 | 129.386 | +3.492 | +2.77 | +3.492 [+2.054, +4.930] | +2.79 [+1.61, +3.97] |
| ruff | Application edit | adapter vs default | 1.933 | 3.666 | +1.733 | +89.63 | +1.606 [+1.521, +2.119] | +85.69 [+68.17, +116.15] |
| ruff | Library edit | adapter vs default | 21.721 | 23.481 | +1.761 | +8.11 | +1.756 [+1.557, +2.013] | +8.10 [+7.20, +9.33] |
| ruff | Fresh build | adapter vs off | 124.587 | 129.386 | +4.799 | +3.85 | +4.799 [+4.416, +5.183] | +3.85 [+3.54, +4.16] |
| ruff | Application edit | adapter vs off | 1.809 | 3.666 | +1.857 | +102.68 | +1.782 [+1.577, +2.215] | +99.87 [+79.91, +128.09] |
| ruff | Library edit | adapter vs off | 21.533 | 23.481 | +1.948 | +9.05 | +2.123 [+1.125, +2.472] | +9.87 [+5.06, +11.76] |
| uv | Fresh build | default vs off | 141.120 | 141.629 | +0.509 | +0.36 | +0.509 [-0.496, +1.514] | +0.36 [-0.35, +1.07] |
| uv | Application edit | default vs off | 7.771 | 7.935 | +0.164 | +2.11 | +0.239 [-0.406, +0.447] | +2.95 [-4.75, +6.26] |
| uv | Library edit | default vs off | 22.664 | 22.750 | +0.086 | +0.38 | +0.078 [-0.320, +0.550] | +0.33 [-1.46, +2.50] |

## Per-round wall time

Each edit value below is one command; the three edits within a round are sequential, not independent rounds.

| Project / comparison / phase | Round | Reference seconds | Candidate seconds | Mean Δ (s / %) |
|---|---:|---|---|---|
| ruff / default vs off / Fresh build | 1 | 124.606 | 127.735 | +3.129 / +2.51% |
| ruff / default vs off / Fresh build | 2 | 124.568 | 124.054 | -0.514 / -0.41% |
| ruff / default vs off / Initial no-op | 1 | 0.986 | 1.001 | +0.014 / +1.46% |
| ruff / default vs off / Initial no-op | 2 | 0.948 | 0.908 | -0.041 / -4.28% |
| ruff / default vs off / Application edit | 1 | 1.930, 1.763, 1.749 | 2.232, 1.871, 1.885 | +0.182 / +10.02% |
| ruff / default vs off / Application edit | 2 | 1.708, 1.973, 1.729 | 1.836, 1.951, 1.824 | +0.067 / +3.73% |
| ruff / default vs off / Library edit | 1 | 21.026, 21.384, 22.207 | 21.660, 21.741, 21.657 | +0.147 / +0.68% |
| ruff / default vs off / Library edit | 2 | 21.643, 21.739, 21.199 | 22.049, 21.636, 21.579 | +0.228 / +1.06% |
| ruff / default vs off / Final no-op | 1 | 0.924 | 0.947 | +0.023 / +2.53% |
| ruff / default vs off / Final no-op | 2 | 0.870 | 0.871 | +0.001 / +0.15% |
| ruff / adapter vs default / Fresh build | 1 | 127.735 | 129.789 | +2.054 / +1.61% |
| ruff / adapter vs default / Fresh build | 2 | 124.054 | 128.984 | +4.930 / +3.97% |
| ruff / adapter vs default / Initial no-op | 1 | 1.001 | 0.907 | -0.094 / -9.39% |
| ruff / adapter vs default / Initial no-op | 2 | 0.908 | 0.970 | +0.062 / +6.83% |
| ruff / adapter vs default / Application edit | 1 | 2.232, 1.871, 1.885 | 3.753, 3.841, 3.460 | +1.689 / +84.62% |
| ruff / adapter vs default / Application edit | 2 | 1.836, 1.951, 1.824 | 3.449, 3.550, 3.944 | +1.777 / +94.98% |
| ruff / adapter vs default / Library edit | 1 | 21.660, 21.741, 21.657 | 23.498, 23.582, 23.332 | +1.784 / +8.23% |
| ruff / adapter vs default / Library edit | 2 | 22.049, 21.636, 21.579 | 23.692, 23.193, 23.592 | +1.738 / +7.99% |
| ruff / adapter vs default / Final no-op | 1 | 0.947 | 0.897 | -0.050 / -5.30% |
| ruff / adapter vs default / Final no-op | 2 | 0.871 | 0.917 | +0.046 / +5.25% |
| ruff / adapter vs off / Fresh build | 1 | 124.606 | 129.789 | +5.183 / +4.16% |
| ruff / adapter vs off / Fresh build | 2 | 124.568 | 128.984 | +4.416 / +3.54% |
| ruff / adapter vs off / Initial no-op | 1 | 0.986 | 0.907 | -0.079 / -8.06% |
| ruff / adapter vs off / Initial no-op | 2 | 0.948 | 0.970 | +0.021 / +2.26% |
| ruff / adapter vs off / Application edit | 1 | 1.930, 1.763, 1.749 | 3.753, 3.841, 3.460 | +1.870 / +103.11% |
| ruff / adapter vs off / Application edit | 2 | 1.708, 1.973, 1.729 | 3.449, 3.550, 3.944 | +1.844 / +102.26% |
| ruff / adapter vs off / Library edit | 1 | 21.026, 21.384, 22.207 | 23.498, 23.582, 23.332 | +1.931 / +8.97% |
| ruff / adapter vs off / Library edit | 2 | 21.643, 21.739, 21.199 | 23.692, 23.193, 23.592 | +1.966 / +9.13% |
| ruff / adapter vs off / Final no-op | 1 | 0.924 | 0.897 | -0.027 / -2.90% |
| ruff / adapter vs off / Final no-op | 2 | 0.870 | 0.917 | +0.047 / +5.40% |
| uv / default vs off / Fresh build | 1 | 141.028 | 140.531 | -0.496 / -0.35% |
| uv / default vs off / Fresh build | 2 | 141.212 | 142.726 | +1.514 / +1.07% |
| uv / default vs off / Initial no-op | 1 | 1.007 | 0.966 | -0.042 / -4.15% |
| uv / default vs off / Initial no-op | 2 | 1.050 | 1.026 | -0.024 / -2.29% |
| uv / default vs off / Application edit | 1 | 8.543, 7.473, 7.138 | 8.137, 7.651, 7.584 | +0.073 / +0.95% |
| uv / default vs off / Application edit | 2 | 8.624, 7.526, 7.323 | 8.885, 7.741, 7.612 | +0.255 / +3.26% |
| uv / default vs off / Library edit | 1 | 23.633, 21.971, 22.381 | 23.828, 21.651, 22.214 | -0.097 / -0.43% |
| uv / default vs off / Library edit | 2 | 23.937, 22.080, 21.983 | 23.898, 22.379, 22.533 | +0.270 / +1.19% |
| uv / default vs off / Final no-op | 1 | 1.037 | 0.972 | -0.065 / -6.25% |
| uv / default vs off / Final no-op | 2 | 0.973 | 0.974 | +0.001 / +0.13% |

## Settled allocation

| Project | Boundary | Comparison | Reference GiB | Candidate GiB | Δ GiB | Δ % |
|---|---|---|---:|---:|---:|---:|
| ruff | Fresh build | default vs off | 2.573 | 2.215 | -0.357 | -13.88 |
| ruff | Final no-op | default vs off | 2.565 | 2.208 | -0.357 | -13.92 |
| ruff | Fresh build | adapter vs default | 2.215 | 2.258 | +0.042 | +1.90 |
| ruff | Final no-op | adapter vs default | 2.208 | 2.250 | +0.042 | +1.91 |
| ruff | Fresh build | adapter vs off | 2.573 | 2.258 | -0.315 | -12.24 |
| ruff | Final no-op | adapter vs off | 2.565 | 2.250 | -0.315 | -12.28 |
| uv | Fresh build | default vs off | 3.510 | 2.854 | -0.656 | -18.68 |
| uv | Final no-op | default vs off | 3.396 | 2.740 | -0.656 | -19.32 |

## CPU and memory

| Project / comparison / phase | CPU mean ref → candidate (s) | CPU Δ % | Largest-child RSS mean ref → candidate (GiB) | Sampled tree RSS mean ref → candidate (GiB) | Tree RSS paired % median [range] |
|---|---|---:|---|---|---|
| ruff / default vs off / Fresh build | 947.820 → 953.420 | +0.59 | 2.105 → 2.018 | 3.851 → 3.795 | -1.45 [-1.96, -0.94] |
| ruff / default vs off / Application edit | 1.633 → 1.635 | +0.10 | 0.310 → 0.316 | 0.741 → 0.624 | -9.79 [-73.28, +112.70] |
| ruff / default vs off / Library edit | 94.893 → 95.043 | +0.16 | 1.715 → 1.720 | 1.782 → 1.781 | +0.05 [-2.38, +1.60] |
| ruff / adapter vs default / Fresh build | 953.420 → 967.205 | +1.45 | 2.018 → 2.048 | 3.795 → 3.899 | +2.74 [+1.69, +3.79] |
| ruff / adapter vs default / Application edit | 1.635 → 3.507 | +114.48 | 0.316 → 0.324 | 0.624 → 0.450 | -13.04 [-68.64, +26.19] |
| ruff / adapter vs default / Library edit | 95.043 → 96.440 | +1.47 | 1.720 → 1.699 | 1.781 → 1.767 | -0.18 [-3.60, +0.70] |
| ruff / adapter vs off / Fresh build | 947.820 → 967.205 | +2.05 | 2.105 → 2.048 | 3.851 → 3.899 | +1.25 [-0.30, +2.81] |
| ruff / adapter vs off / Application edit | 1.633 → 3.507 | +114.69 | 0.310 → 0.324 | 0.741 → 0.450 | -41.91 [-71.75, +123.96] |
| ruff / adapter vs off / Library edit | 94.893 → 96.440 | +1.63 | 1.715 → 1.699 | 1.782 → 1.767 | -0.93 [-2.07, +0.95] |
| uv / default vs off / Fresh build | 856.835 → 862.970 | +0.72 | 2.085 → 2.108 | 3.176 → 3.320 | +4.51 [+3.14, +5.89] |
| uv / default vs off / Application edit | 8.132 → 7.867 | -3.26 | 1.278 → 1.279 | 1.325 → 1.387 | +4.02 [-7.58, +21.67] |
| uv / default vs off / Library edit | 42.468 → 42.388 | -0.19 | 1.170 → 1.172 | 1.432 → 1.416 | +0.16 [-30.44, +24.87] |

## Scope and limits

- Wall time covers each Cargo command. Runtime oracles, census and cleanup run outside that boundary. No-op rows are retained above and were checked for zero compiler/replay invocations and unchanged executable hashes.
- Allocation includes target/build/scratch and deduplicates hardlinks; it is settled reachable allocation, not peak disk or unique physical CoW extents. Each lane was censused before owned cleanup. Transient adapter decode storage is not measured.
- GNU time reports the largest individual child RSS peak. Sampled tree RSS sums live processes and can count shared mappings repeatedly or miss short peaks; it is not unique physical memory or PSS. Both remain reported without attributing their difference.
- Means, paired medians/ranges, and both fresh-round distributions are descriptive. The six edit observations are not six independent rounds, and there are no confidence or universal-regression claims.
- Non-PGO/BOLT compiler; no cold OS-cache claim. Fixed jobs=8 and the recorded profiles/trust options apply. LTO/plugin/DWARF runtime compatibility is established separately, not timed here.
- Source restoration and lane cleanup are verified from archived receipts and source manifests; removed lane bytes cannot be re-read. Raw rows and referenced logs are retained. No failed row is excluded.

Exact sources and binary identities are in `summary.json`; raw rows are copied byte-for-byte to `samples.jsonl`. This report computes results, not an adoption decision.
