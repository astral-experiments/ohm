# Metadata-prefix reuse: removal results

**Recommend removing Rust #57 coherently, accepting the measured first-edit costs.** Removing the metadata-prefix protocol deletes 702 net production lines. It makes Ruff’s first edit 295 ms slower and uv’s first edit 643 ms slower in these two-pair screens. Other results are mixed, including faster Codex no-op and second-edit commands. The recommendation weighs those real command costs against an additional metadata format, producer/consumer state and work-product protocol. Final root command, archive, proof and current-closure reviews passed.

Each project has two independent pairs, in opposite arm orders. Both arms run the same five `cargo check --lib --locked --offline` commands with eight jobs: cold, warm no-op, and the three original fixture edits. Each arm starts from empty target and shared histories; prepared source inputs are reused. Positive deltas below mean removal is slower. Medians are computed from within-pair deltas. With only two pairs, the ranges describe the observations and do not establish precise effects or workflow frequency.

| Project | State | Full median (s) | Removal median (s) | Paired delta (ms) | Observed delta range (ms) | Removal slower |
|---|---|---:|---:|---:|---:|---:|
| ruff | cold | 29.092 | 28.768 | -324.0 | -1420.9 to +773.0 | 1/2 |
| ruff | warm no-op | 0.604 | 0.669 | +65.6 | -213.5 to +344.8 | 1/2 |
| ruff | edit 1 | 7.859 | 8.154 | +295.4 | +105.2 to +485.6 | 2/2 |
| ruff | edit 2 | 9.858 | 9.494 | -363.9 | -929.9 to +202.1 | 1/2 |
| ruff | edit 3 | 10.234 | 10.038 | -195.9 | -216.2 to -175.6 | 0/2 |
| uv | cold | 53.554 | 53.973 | +418.8 | -1373.8 to +2211.4 | 1/2 |
| uv | warm no-op | 0.879 | 1.025 | +146.0 | -25.3 to +317.2 | 1/2 |
| uv | edit 1 | 5.732 | 6.375 | +643.1 | +633.0 to +653.2 | 2/2 |
| uv | edit 2 | 1.817 | 1.845 | +27.9 | -151.4 to +207.3 | 1/2 |
| uv | edit 3 | 4.844 | 5.138 | +293.5 | -117.5 to +704.6 | 1/2 |
| codex | cold | 151.220 | 151.190 | -29.8 | -393.0 to +333.5 | 1/2 |
| codex | warm no-op | 2.330 | 2.198 | -131.9 | -157.1 to -106.7 | 0/2 |
| codex | edit 1 | 8.879 | 8.701 | -177.4 | -364.9 to +10.2 | 1/2 |
| codex | edit 2 | 6.444 | 6.233 | -211.1 | -228.5 to -193.6 | 0/2 |
| codex | edit 3 | 7.277 | 7.276 | -0.4 | -508.8 to +507.9 | 1/2 |

Ruff’s third edit is faster in both pairs, by 176–216 ms. Codex’s no-op and second edit improve by 107–157 ms and 194–229 ms. Ten of the fifteen observed delta ranges cross zero. The uv first-edit loss is 633–653 ms, and the Ruff first-edit loss is 105–486 ms. Those losses are retained in the recommendation; no combined speedup across unrelated commands is claimed.

The coherent patch is +26/−728 across seven production files. It removes the prefix encoder, incremental work-product state, producer/consumer reuse and dep-graph integration together. Complete metadata reuse and public API hashes remain. Sparse metadata #123, its lookup/format tests, coroutine metadata and serialized query caches remain. This screen therefore measures #57’s prefix family rather than attributing effects to sparse tables or other cache removals. The test-only `encoded_range` helper remains for #123’s format checks.

The optimized removal is source commit `788b2716e2a74b3e233b55843a02d26ee996b5e4`, tree `7a602be9494bfbc18e06b14fa1b40f7d1280739f`; the full source is `348339ddae4288ebb3af97d204b19479fef8f5f2`. Both frozen runtimes keep their own accepted four PGO profiles and BOLT profile, release config and exact source/training inputs. Eleven training commands match as a multiset and seven non-formatter commands match in order; four standalone formatter batches have no ordered-equality claim. The original 66,170 shipping files per arm and 3,689 exact Rust-src additions were verified in the current 69,859-file maps, with own modes and loading, unique inodes within each arm and no cross-arm aliasing.

Focused native validation includes 26 reduced compiletests, three compiler source unit cases, 44 linked history executions, fifteen header fallbacks and two foreign-payload observations. The full arm reuses its exact accepted 25-compiletest/three-unit receipt; the baseline common suite was not rerun on oss7. Source unit tests separately enable debug assertions with LTO off and do not establish shipping assertions. The selected representative commands are library checks: final executable linking, full suites, worktree creation frequency and whole-stack interactions are outside this timing screen.

All six pairs have successful command/status, source/lock and output parity checks, 60 timed commands, 1,074 continuous guard samples and 96 required quiet samples. The raw command logs are hash-bound; exact warning-text equality is not claimed. Every recorded pair and release is retained. One Ruff startup failed before any timer because its fixture path used the private method directory; its exact status and traceback are preserved, and only that zero-timer record is excluded from accepted command matching. Completion GET timeouts/HTTP 503 errors were resolved using the same retained execution IDs, with no duplicate dispatch.

Evidence: [complete raw manifest](complete-raw-retrieved-ssh-01/packet/validation/prefix-complete-01/packet.json), [all command statistics](prefix-complete-command-self-review-01.json), [root command audit](prefix-final-command-root-review-01.json), [44-proof body audit](prefix-final-proof-self-review-01.json), [actual readiness root review](prefix-actual-root-review-01.json), [collector approval](prefix-final-collector-root-review-01.json), [final root acceptance](prefix-final-root-review-01.json).
