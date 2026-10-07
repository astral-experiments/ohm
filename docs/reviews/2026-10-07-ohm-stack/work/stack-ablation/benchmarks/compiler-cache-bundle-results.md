# Compiler worker caches and serialized-query retention

Hold the coherent removal and retain this family provisionally. Removing 692 net lines costs a paired median 5.97 seconds on Codex's cold library check, with all six pairs slower (range +0.64 to +11.53 seconds). The paired percentage median is 3.96%. Warm Codex no-op and edit results are mixed. Ruff and uv have no command state whose six-pair range stays on one side of zero.

This supports the family on the measured cold Codex workload. It does not establish that every cache, generation, identity alias or compaction path earns its maintenance cost. The small and mixed warm effects deserve scrutiny. The separate Clippy ablation's cache-mapping panic also remains an open correctness question; this successful comparison does not resolve it or isolate Rust #106. If pursuing further simplification here, split the owning mechanisms before defending or removing them individually. No extra split campaign has been started.

## Scope and commands

The fixed removal combines Rust #83, #88, #106 and #107 and the resolver trait-scope cache; it preserves #105's promotion index. The exported patch changes 19 files, +47/-739, for 692 net removed lines. Those totals include tests and release workflow changes. Full and reduced use their accepted optimized compiler profiles; Cargo, training inputs and non-axis defaults are fixed.

Each project has six independent pairs, three in each order. Every arm starts from an empty private target and shared build store, then runs cold, no-op and three recorded edited states with eight jobs. There are no additional warmups or project test executions. The commands, run at each arm's workspace root (Codex's `codex-rs` workspace), are:

- Ruff: `cargo +<arm> check --locked --offline --lib -p ty_python_semantic -p ty_python_core`
- uv: `cargo +<arm> check --locked --offline --lib -p uv-pypi-types -p uv-client`
- Codex: `cargo +<arm> check --locked --offline --lib -p codex-tui`

The Ruff edits change recursive/implicit attribute inference; uv's first two edits change the Simple API JSON parser and the third changes compatibility tests; Codex's edits change active-cell layout bookkeeping, rendering and invalidation. The uv test-only third edit may be inactive for this selected library check. Exact patches, source inventories, locks, argv, logs and profiles are retained in the raw evidence.

## Every measured command state

Positive deltas mean removal was slower. The delta is the median of pairwise removal-minus-full differences; it need not equal the difference of the arm medians. The range is the observed six-pair range, not a confidence interval. Project estimates are kept separate; Ruff/uv's complete OpenAI1 block and Codex's complete Serc314O1 block are not pooled across hosts.

| Project | State | Full median | Removed median | Paired median delta | Paired range | Slower pairs |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ruff | Cold | 27.304 s | 27.972 s | +0.546 s | -1.319 to +1.754 s | 5 / 6 |
| ruff | Warm no-op | 0.420 s | 0.439 s | +0.010 s | -0.295 to +0.413 s | 3 / 6 |
| ruff | Edit 1 | 8.539 s | 8.643 s | +0.469 s | -1.234 to +1.565 s | 4 / 6 |
| ruff | Edit 2 | 9.829 s | 10.009 s | +0.117 s | -0.297 to +0.348 s | 4 / 6 |
| ruff | Edit 3 | 10.621 s | 11.171 s | +0.561 s | -0.426 to +1.141 s | 5 / 6 |
| uv | Cold | 47.561 s | 47.740 s | +0.041 s | -0.436 to +1.774 s | 3 / 6 |
| uv | Warm no-op | 0.658 s | 0.762 s | +0.105 s | -0.064 to +0.264 s | 4 / 6 |
| uv | Edit 1 | 5.006 s | 4.888 s | -0.151 s | -0.481 to +0.764 s | 2 / 6 |
| uv | Edit 2 | 1.407 s | 1.471 s | +0.096 s | -0.147 to +0.345 s | 5 / 6 |
| uv | Edit 3 | 4.423 s | 4.401 s | +0.007 s | -0.549 to +0.701 s | 3 / 6 |
| codex | Cold | 151.737 s | 156.830 s | +5.971 s | +0.637 to +11.533 s | 6 / 6 |
| codex | Warm no-op | 2.456 s | 2.670 s | +0.002 s | -1.241 to +0.811 s | 3 / 6 |
| codex | Edit 1 | 8.727 s | 8.961 s | +0.117 s | -1.128 to +0.873 s | 4 / 6 |
| codex | Edit 2 | 6.630 s | 6.438 s | -0.009 s | -0.747 to +0.194 s | 3 / 6 |
| codex | Edit 3 | 7.486 s | 7.406 s | -0.144 s | -0.561 to +0.945 s | 2 / 6 |

## Acceptance and evidence

All 18 accepted pairs, 180 commands and 15 statistics passed the independent root raw audit. It rechecked 3,237 continuous monitor samples and 288 required quiet samples, accepted pointers, exact control snapshots, logs, source/lock parity, actual successful supervisor exits and positive child/group/lease release. Required quiet windows and continuous noise thresholds are unchanged. Rejected and interrupted attempts are preserved and excluded whole; no partial command was imported. A malformed earlier uv transport pointed at the prior Ruff output and was rejected; the successful launch is matched by project, slot, attempt and output together.

Maximum child RSS is retained per command in the raw statistics and is not aggregate process memory. Raw log hashes and successful statuses establish the reported parity scope; they do not establish exact warning-text equivalence. Accepted source, native and PGO evidence is reused, without another compiler build or native suite. Codex's original control bodies were reconstructed from retained validated snapshots and match the frozen original hashes exactly; the reconstruction is explicitly recorded outside the retrieved raw packet.

Removal reduces median paired maximum-child RSS in every compiling state, by 11.6–157.6 MiB; warm no-op differences are below 1 MiB. All six pairs use less RSS in eleven of the twelve compiling states, with five of six agreeing on uv edit 2. That memory benefit strengthens the case for a smaller implementation, although it does not erase the cold Codex time cost. [Every RSS state](compiler-bundle-resume-01/compiler-bundle-max-child-rss-01.json).

[Final root review and all cells](compiler-bundle-resume-01/compiler-bundle-complete-root-review-01.json), [Ruff/uv independent audit](compiler-bundle-resume-01/independent-complete-ruff-uv-review-01.json), [Codex independent audit](bundle-codex-serc314-migration-01/independent-complete-codex-review-01.json), [Ruff/uv archive verification](cgu-inplace-openai1-two-pair-01/original-bundle12-raw-archive-api-03/root-extraction-review-01.json), [Codex archive verification](bundle-codex-serc314-migration-01/complete-bundle-codex-raw-archive-api-01/root-extraction-review-01.json).
