# rustfmt #18: first accepted ablation results

Removing config snapshot reuse costs a few milliseconds on warm formatting in these workspaces. This result does not establish a benefit large enough to justify the native identity and hash-reuse state. These six paired formatting histories now supply primary affected-operation evidence; repeating entire development sessions is not a required first-pass gate. The removal recommendation remains provisional until the cross-candidate decisions are assembled.

Six counterbalanced pairs per project on charlie-openai-3, Linux x86_64, jobs 8. Each arm ran the same 17-command formatting history from an empty task-owned cache. All outputs and 612 formatted-source proofs matched; the continuous host guard passed all 737 samples. Original optimized source, own PGO profiles and component runtimes are bound in the evidence packet. No runs or outliers were trimmed.

Positive deltas below mean removing #18 was slower. Whole-history values are the median of six paired differences, rather than the difference between two medians.

| Project | Full history median | Removed history median | Paired removal delta | Paired delta range | Warm format delta | Warm check delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ruff | 27.887 s | 27.923 s | -56.2 ms (-0.20%) | -428.9 to +282.7 ms | +0.81 ms | +1.70 ms |
| uv | 12.066 s | 12.227 s | +164.4 ms (+1.36%) | +56.6 to +292.0 ms | +2.97 ms | +1.20 ms |
| codex | 58.717 s | 58.673 s | -34.5 ms (-0.06%) | -144.5 to +45.6 ms | +3.44 ms | +3.80 ms |

uv loses 164 ms across a roughly 12-second history, consistently across the six pairs. Ruff and Codex show mixed whole-history deltas, with no consistent loss. The warm-format penalty is 0.8–3.4 ms; some edit phases show larger or noisy effects. Exact per-command medians and ranges are in `no18-supp07-root-results.json`.

The config edit writes explicit width 100 while preserving each project's effective formatting. It measures invalidation and reuse, not config-heavy fanout or a formatting-width change. Dirty one-leaf edits take package fallback; native and generated tests cover the retained single-leaf path separately. These results do not generalize to an unmeasured config-heavy workspace.

The isolated reversal is one file, +24/-189, and preserves multi-leaf batching and package caching. Maximum child RSS and endpoint allocated-byte medians are retained in the JSON; they are neither aggregate process memory nor peak disk use. Earlier failed or contaminated campaigns remain separate and preserved.

Evidence: `rustfmt-no-config-snapshot-supplementary-07-accepted/`, accepted archive SHA256 `6df7d271484f8a47ef96a134f9b20b90c7c3c3433b84511eda3bde62a06d17a4`, root verification and statistics `no18-supp07-root-results.json` (SHA256 `34c315d593d159f17f7211a8f5fdffe675b0f07439a217b798e40714e0bdf3f0`).
