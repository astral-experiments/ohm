# No19 independent review

The completed comparison supports removing the multi-leaf batch protocol under the simplification goal, with an explicit cost: clean four-leaf edits take about **131 ms longer in Ruff and 50 ms longer in uv**. That benefit is real and consistent across all six pairs. The large, mechanically attributed benefit is on the already-formatted leaf path in these fixtures; native traces show no No19 batching for the selected Codex phases. The removal cuts 243 net production lines and 86 net feature-test lines.

Each command is actual `cargo fmt --all` or `cargo fmt --all -- --check` on the pinned real project. Source edits are controlled fixture comments and formatter configuration changes; their frequency in developer work is unknown. Full-session totals are context only. No new benchmark or correctness tests were run during review.

Values below are full → removed-arm median milliseconds. Delta is the median of six paired removed-minus-full values; brackets show the complete paired range, without outlier filtering. A positive delta means removal costs time.

| Phase | Project | Median ms | Paired delta ms [range] |
| --- | --- | ---: | ---: |
| Warm no-op format | ruff | 224.9 → 224.1 | -1.1 [-6.0, +3.2] |
| Warm no-op format | uv | 148.4 → 148.3 | +0.4 [-2.1, +4.8] |
| Warm no-op format | codex | 368.5 → 367.9 | -1.6 [-17.8, +28.0] |
| Warm no-op check | ruff | 223.7 → 226.0 | +1.9 [-0.9, +6.7] |
| Warm no-op check | uv | 148.9 → 148.9 | +0.0 [-1.5, +1.2] |
| Warm no-op check | codex | 367.6 → 374.7 | +6.8 [-4.7, +37.7] |
| Dirty one-leaf format | ruff | 833.2 → 837.7 | +7.3 [-6.1, +10.8] |
| Dirty one-leaf format | uv | 384.1 → 388.3 | +4.8 [+1.3, +9.2] |
| Dirty one-leaf format | codex | 4773.3 → 4790.8 | +13.9 [-12.7, +119.7] |
| Dirty four-file format | ruff | 834.8 → 827.2 | -8.3 [-21.5, +16.5] |
| Dirty four-file format | uv | 385.2 → 393.7 | +6.9 [+3.3, +10.5] |
| Dirty four-file format | codex | 4798.3 → 4802.0 | +18.8 [-65.5, +100.3] |
| Already-formatted four-leaf format | ruff | 394.4 → 527.6 | +131.4 [+124.6, +143.2] |
| Already-formatted four-leaf format | uv | 220.8 → 270.5 | +50.0 [+46.0, +53.2] |
| Already-formatted four-leaf format | codex | 2573.4 → 2572.1 | -4.9 [-30.7, +41.0] |
| Four-file fallback format | ruff | 4236.2 → 4210.9 | -23.2 [-45.8, -2.4] |
| Four-file fallback format | uv | 385.7 → 388.5 | +1.8 [-6.2, +11.5] |
| Four-file fallback format | codex | 4758.3 → 4781.3 | +19.9 [-19.9, +46.8] |
| Configuration edit format | ruff | 6325.5 → 6306.0 | -28.3 [-121.1, +105.3] |
| Configuration edit format | uv | 2969.0 → 2986.9 | +1.1 [-19.0, +80.5] |
| Configuration edit format | codex | 11395.8 → 11310.6 | -100.9 [-176.8, +185.1] |
| Configuration revert format | ruff | 6274.0 → 6275.3 | +19.4 [-303.2, +72.6] |
| Configuration revert format | uv | 2978.4 → 2978.3 | -1.2 [-12.3, +6.7] |
| Configuration revert format | codex | 11303.9 → 11363.5 | +48.0 [-346.8, +300.8] |

Small positive differences are also preserved: uv dirty one-leaf and dirty four-file formatting add paired medians of 4.8 ms and 6.9 ms, respectively, with all six pairs positive. Those small gains do not change the complexity recommendation. On the clean four-leaf path, removing batching costs **33.3%** in Ruff (range 31.0–36.9%) and **22.7%** in uv (20.7–24.1%). That percentage should accompany the absolute 131/50 ms cost. Every other phase, including first-format and all checks, is retained with all six raw paired values in `independent-statistics.json`; none is discarded.

For context, the seventeen-command sums have paired removal penalties of Ruff 127.5 ms (+0.46%, range −243.9…184.4ms), uv 82.4 ms (+0.69%,48.1…145.8ms), and Codex 94.7 ms (+0.16%,−415.8…758.4ms). These include deliberately expensive cold/configuration formatting and do not estimate a normal developer-session speedup.

I rehashed all 2,004 raw archive files (229,922,657 uncompressed bytes) and 39 readiness proofs. I recomputed 36 histories, 612 successful commands, 18 complete pairs, each command’s formatted Rust-source parity, and final source byte/mode parity. All 36 clean-four-file edits have exactly the same source hashes before and after formatting. The native raw stderr confirms full-arm batch reuse for Ruff/uv clean-four-file phases and none for the reduced arm; dirty leaves use fallback, and Codex uses fallback in both arms. Retained native summaries are full 381 passed/0 failed/1 ignored, reduced 377/0/1; removed feature tests explain the different counts. Accepted own-PGO/build/source packets remain explicit dependencies.

Both 69,859-file runtime maps differ only in `rustfmt`/`cargo-fmt`; current loader receipts bind all seven tools and their own private compiler/LLVM dependencies. The accepted d4 wrapper rehashes runtimes before/after the guarded campaign. The copied worker readiness includes verified-file maps; removing only those derived dictionaries reproduces the exact originally authorized df44 hash.

The unchanged guard has 743 samples and zero violations, with both six-sample quiet preflights passing. Counterbalanced order and 36 empty donors are verified. All 1,224 archived timed log/RSS timestamps lie inside this campaign’s monitor window, every raw path belongs to this campaign, and no failed-campaign cells appear. The monitor samples every two seconds and cannot exclude every short competing process. Maximum-child RSS is not aggregate memory; no memory conclusion is drawn.

Recommendation: accept the measured narrow cost and remove No19 for a smaller formatter protocol. Retaining it would need evidence that already-formatted multi-file edits occur often enough to justify the complexity. This review establishes no universal formatting or full-session benefit across other projects, configurations or platforms.
