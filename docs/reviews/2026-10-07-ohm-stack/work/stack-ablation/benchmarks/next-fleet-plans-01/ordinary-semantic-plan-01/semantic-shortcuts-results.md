# Semantic shortcuts #84/#110/#117: final command findings

**Remove the coherent shortcut family**, accepting the measured costs in Ruff's third edit and Codex's warm no-op. The removal drops 464 net production lines across 15 files (+45/-509). Removing it costs a paired median 0.400 s in Ruff's third edit and 0.550 s in Codex's warm no-op, with both pairs slower. It improves uv's first and second edits by 0.224 / 0.413 s and Codex's third edit by 0.357 s, with both pairs faster. Other observed ranges cross zero. These small and mixed results do not justify the maintenance cost under the requested simplification goal. They do establish costs worth accepting explicitly.

The screen is finally accepted: six pairs, 60 original checks and all fifteen states, with 1,086 continuous monitor and 96 required quiet samples. [Final root review](semantic-final-root-review-01.json) binds all 640 raw payloads, 48 source/runtime/native proofs and the positive timing/capture/reader release. No individual #84, #110 or #117 effect is attributed from this coherent removal.

## Representative command timing

Both arms use the same original Cargo bytes, source bases, selected libraries, eight jobs and private target histories. Each history runs the five original `cargo check` commands: cold, warm no-op and a check after each of three edits. Two pairs per project use opposite arm orders on OpenAI2. Project tests are never executed. Positive removal deltas mean slower; each range contains both observed pairs. Arm medians, medians of paired differences and medians of paired percentages are separate calculations.

| Project and state | Full median | Removed median | Median paired removal delta | Paired range | Paired percent median | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ruff, Cold check | 27.790 s | 27.739 s | -0.051 s | -0.350 to +0.248 s | -0.19% | 1/2 |
| Ruff, Warm no-op | 0.438 s | 0.665 s | +0.227 s | -0.037 to +0.490 s | +51.90% | 1/2 |
| Ruff, Original edit 1 | 8.273 s | 8.728 s | +0.455 s | -0.160 to +1.071 s | +5.86% | 1/2 |
| Ruff, Original edit 2 | 9.805 s | 9.835 s | +0.030 s | -0.059 to +0.119 s | +0.32% | 1/2 |
| Ruff, Original edit 3 | 10.874 s | 11.274 s | +0.400 s | +0.361 to +0.438 s | +3.68% | 2/2 |
| Uv, Cold check | 48.677 s | 48.851 s | +0.174 s | -0.542 to +0.890 s | +0.38% | 1/2 |
| Uv, Warm no-op | 0.949 s | 1.054 s | +0.106 s | -0.006 to +0.218 s | +12.58% | 1/2 |
| Uv, Original edit 1 | 5.307 s | 5.083 s | -0.224 s | -0.305 to -0.144 s | -4.23% | 0/2 |
| Uv, Original edit 2 | 1.778 s | 1.365 s | -0.413 s | -0.604 to -0.223 s | -22.87% | 0/2 |
| Uv, Original edit 3 | 4.996 s | 4.885 s | -0.112 s | -0.233 to +0.009 s | -2.18% | 1/2 |
| Codex, Cold check | 144.778 s | 144.844 s | +0.067 s | -0.446 to +0.579 s | +0.05% | 1/2 |
| Codex, Warm no-op | 2.201 s | 2.751 s | +0.550 s | +0.208 to +0.893 s | +24.81% | 2/2 |
| Codex, Original edit 1 | 9.641 s | 9.477 s | -0.164 s | -0.885 to +0.556 s | -1.18% | 1/2 |
| Codex, Original edit 2 | 7.341 s | 7.395 s | +0.054 s | -0.214 to +0.323 s | +0.72% | 1/2 |
| Codex, Original edit 3 | 7.397 s | 7.040 s | -0.357 s | -0.367 to -0.346 s | -4.83% | 0/2 |

Two pairs per project are screening evidence, without a statistical significance claim or a workload-frequency estimate. Absolute times matter for short no-op states: Codex's percentage loss describes the observed 0.550 s cost, not a large compilation cost. The edited states and projects cannot be summed into a stack-wide gain. uv's third edit concerns tests and may be inactive under the selected library recipe.

## Maximum child-process memory

GNU time's maximum child RSS is the largest observed child-process resident set, not aggregate concurrent-process memory or a whole-pipeline peak. Each delta below is removed minus full within the same pair, in MiB. The two observed differences are retained even when the median is small.

| Project and state | Median paired maximum-child RSS delta | Paired range | Increased pairs |
| --- | ---: | ---: | ---: |
| Ruff, Cold check | -1.52 MiB | -13.55 to +10.51 MiB | 1/2 |
| Ruff, Warm no-op | -0.06 MiB | -0.12 to -0.00 MiB | 0/2 |
| Ruff, Original edit 1 | -7.47 MiB | -13.27 to -1.66 MiB | 0/2 |
| Ruff, Original edit 2 | -21.21 MiB | -29.74 to -12.69 MiB | 0/2 |
| Ruff, Original edit 3 | -6.31 MiB | -25.09 to +12.47 MiB | 1/2 |
| Uv, Cold check | +15.25 MiB | +7.67 to +22.84 MiB | 2/2 |
| Uv, Warm no-op | +0.25 MiB | +0.12 to +0.37 MiB | 2/2 |
| Uv, Original edit 1 | -5.64 MiB | -10.98 to -0.30 MiB | 0/2 |
| Uv, Original edit 2 | +3.49 MiB | -0.15 to +7.12 MiB | 1/2 |
| Uv, Original edit 3 | +0.04 MiB | -10.08 to +10.17 MiB | 1/2 |
| Codex, Cold check | +6.13 MiB | -6.22 to +18.49 MiB | 1/2 |
| Codex, Warm no-op | +0.31 MiB | +0.23 to +0.39 MiB | 2/2 |
| Codex, Original edit 1 | +16.28 MiB | +5.13 to +27.42 MiB | 2/2 |
| Codex, Original edit 2 | -8.83 MiB | -10.16 to -7.50 MiB | 0/2 |
| Codex, Original edit 3 | -0.67 MiB | -7.57 to +6.24 MiB | 1/2 |

Removal raises uv cold maximum-child RSS by a paired median 15.25 MiB and Codex first-edit RSS by 16.28 MiB, in both pairs. It lowers Ruff first/second-edit RSS by 7.47 / 21.21 MiB and Codex second-edit RSS by 8.83 MiB, in both pairs. Other states vary. These modest, mixed process-level changes are accepted in the simplification recommendation; no aggregate memory benefit or additive memory saving is claimed. [Independent paired-statistic recomputation](semantic-all-project-paired-statistics-self-review-01.json) includes every original timing and RSS cell.

## Source, correctness and provenance

[The coherent source removal](../../../variants/rust/ordinary-semantic.patch) replaces the three shortcut mechanisms together. It does not isolate each PR. The optimized compiler, original eleven training-command multiset, seven ordered non-formatter training commands, own four PGO inputs and BOLT input, native controls and source identities remain accepted and unchanged. Both current 69,859-file runtime maps retain the original 66,170-file shipping cores, own modes/sizes and unique inodes, with no cross-arm sharing. Fourteen own loader graphs cover normal and replay environments. Host migration did not repeat a native suite, optimized build or training run.

Broad UI validation originally recorded 3,582 passes, one failure and eight ignored cases for the full control, versus 3,583 passes, zero failures and the same eight ignored cases for the removal. The full control's `tests/ui/traits/final/overriding-rpitit.rs` ICE recurred in all three focused repetitions; the removal passed all three. Both arms passed the sixteen selected incremental cases. Reduced source units and linked/header/foreign-payload checks also passed. These facts support the coherent removal; they do not prove which member caused the ICE or claim the full control passed all correctness checks. [Original independent native review](../../../variants/rust/receipts/ordinary-semantic/native/independent-review.json) preserves that limit.

Old oss8 whole-pair interference failures remain excluded. The OpenAI2 supervisor's first dispatch failed before any timed command because it pinned the scratch root. Its exact zero-timer log/configuration and positive closure are preserved; the already accepted TMP supervisor corrected that path. UV slot 1's completion request timed out and was recovered from the same execution without repeating a timed command. No partial pair was stitched into an accepted result. Final ownership checks proved every timing, collector and archive-reader group, protected user, compiler, lease and lock closed before the host was handed to MSRV.

[Root command audit](semantic-complete-command-root-review-01.json), [complete raw manifest](complete-raw-retrieved-ssh-01/packet/validation/semantic-openai2-complete-01/packet.json), [final positive closure](final-archive-readers-current-release-actual-ssh-03/decoded.json) and [final root acceptance](semantic-final-root-review-01.json) preserve the exact evidence. A future combined lean-stack comparison remains separate from these per-candidate conclusions.
