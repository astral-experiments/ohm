# Sparse metadata #123: complete command and memory findings

All eighteen accepted pairs are now command and proof audited: six Ruff and six uv pairs on OpenAI2, and six new Codex pairs on Direct2. Every one of the fifteen observed latency ranges crosses zero. Removing sparse metadata repeatedly increases maximum-child RSS: about 16–40 MiB in several Ruff/uv states and 60 MiB for Codex cold compilation and the first edit. **Remove, accepting the measured memory and storage cost.** The removal drops 144 net production lines, plus 176 feature-test lines, and eliminates the custom wire-format, rank, bounds and export/replay protocol. Cold/first-edit maximum-child RSS costs are about 1–4% of the measured process, while all latency ranges cross zero. Under the requested simplification goal, that measured cost is worth accepting. Retaining the feature would be reasonable if these memory savings were an explicit priority.

Each project's pairs remain on one host. Ruff/uv and Codex are reported as separate host blocks; their samples are never pooled into a cross-host estimator. The final current OpenAI2 capture/reader closure passed after both complete archives were retrieved. [Final root acceptance](dense-final-root-review-01.json) passed both raw blocks, all eighteen command pairs, source/runtime/native proofs and the exact current closure. Earlier isolated Codex samples on OpenAI2 and Serc841 remain excluded; their historical launch metadata is retained in the original raw archive for audit.

## Current audited Codex command times

Both arms use the same original Cargo bytes, source bases, selected TUI library, eight jobs, private target histories and the original five `cargo check` commands: cold, warm no-op and one check after each of three edits. Slots alternate full/reduced then reduced/full. Project tests are not executed. Positive deltas mean the removal is slower. Arm medians and medians of pairwise differences are calculated separately; ranges contain every pair.

| State | Full median | Removed median | Median paired removal delta | Paired range | Paired percent median | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cold check | 122.987 s | 122.655 s | -0.695 s | -12.434 to +2.231 s | -0.57% | 2/6 |
| Warm no-op | 2.048 s | 2.275 s | +0.148 s | -0.919 to +0.746 s | +6.89% | 5/6 |
| Original edit 1 | 7.471 s | 7.692 s | +0.179 s | -0.336 to +0.407 s | +2.43% | 4/6 |
| Original edit 2 | 5.634 s | 5.716 s | +0.075 s | -0.178 to +0.881 s | +1.34% | 4/6 |
| Original edit 3 | 5.680 s | 5.672 s | +0.031 s | -0.526 to +0.891 s | +0.55% | 4/6 |

All five timing ranges cross zero; no statistical significance claim is made. The cold median is 0.695 s faster without the feature, but its range spans a 12.434 s improvement and 2.231 s loss. Warm/edit paired medians range from +31 to +179 ms. These ordinary-command results do not establish a whole-workflow speedup or the frequency of these edited states.

## Memory costs

GNU time reports the maximum resident set size of a child process. It does not sum concurrent process memory or establish whole-pipeline peak RSS. The following figures are medians and ranges of within-pair removed-minus-full differences, divided by 1,024 to convert KiB to MiB. They are not differences of arm medians.

| State | Median paired maximum-child RSS delta | Paired range | Increased pairs |
| --- | ---: | ---: | ---: |
| Cold check | +59.59 MiB | +46.89 to +92.64 MiB | 6/6 |
| Warm no-op | +0.24 MiB | -0.51 to +0.42 MiB | 4/6 |
| Original edit 1 | +60.55 MiB | +36.26 to +86.48 MiB | 6/6 |
| Original edit 2 | +31.15 MiB | -15.48 to +68.90 MiB | 5/6 |
| Original edit 3 | +9.54 MiB | -8.34 to +43.79 MiB | 4/6 |

Cold and first-edit removal increase this metric in every pair. Later edits are mixed. The Codex full-control process medians are about 2,015 MiB cold and 1,955 MiB after the first edit; removal adds about 60 / 61 MiB, or roughly 3%. Ruff cold/first-edit full medians are about 1,876 / 1,683 MiB with 34 / 16 MiB costs; uv is about 753 / 756 MiB with 29 / 27 MiB costs. These are approximately 1–4% of the measured process, without an aggregate RSS claim. Historical settled target-disk savings were 1.84–2.64%; endpoint disk bytes do not establish peak disk use. The final recommendation accepts these memory and storage costs for a simpler upstream divergence; near-zero latency does not erase them.

## Scope, source and verification

This variant reverses Rust #123 sparse metadata through [the coherent removal patch](../../variants/rust/dense-metadata.patch). The removal changes six files, +41/-361 total: 144 net production lines and 176 test lines removed. It changes metadata representation and export/replay handling together. It preserves independent runtime/source identities, compiler cache policies and the original release PGO/BOLT inputs. The comparison does not attribute costs to individual encoding operations.

Direct2 actual readiness binds both current 69,859-file runtime maps, own modes/sizes and unique inodes with no cross-arm sharing, fourteen own tool-loading graphs, source fixtures, private temporary-directory controls and 105 proof bodies. Eighty original source, training, profile and native proofs are unchanged from the accepted compiler preparation. No optimized compiler build, training or native suite was repeated for migration.

The complete new raw packet contains 737 payloads and 738 safe regular members. All body hashes and original tar modes were independently rechecked. The final command audit covers six accepted pairs, 60 original checks, five state statistics, 1,487 continuous monitor samples and 144 required quiet samples, with source/lock/command/output parity and positive releases. The host is positively released after raw capture and immutable archive retrieval. Earlier failed or contaminated attempts remain excluded and preserved. Warning parity uses the accepted diagnostic/source scope; it does not assert byte-identical timing log text.

[Root command review](dense-new-six-codex-command-root-review-01.json), [root proof review](dense-new-six-codex-proof-root-review-01.json), [independent command statistics and all six raw cells](dense-new-six-codex-results-self-review-01.json), [complete raw packet](complete-six-codex-raw-retrieved-ssh-01/packet/validation/dense-direct2-codex-complete-01/packet.json) and [positive current release](final-current-release-actual-ssh-01/decoded.json) preserve the exact bindings.

## Original Ruff and uv block

The original twelve Ruff/uv pairs on OpenAI2 are fully audited. Each uses the same selected libraries, eight jobs, original five `cargo check` commands and alternating arm order. Positive removal deltas mean slower. All ten timing ranges cross zero; the medians below are differences within pairs, calculated independently of the arm medians.

| Project and state | Full median | Removed median | Median paired removal delta | Paired range | Paired percent median | Slower pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ruff, Cold check | 27.550 s | 26.357 s | -0.875 s | -1.831 to +0.528 s | -3.18% | 1/6 |
| Ruff, Warm no-op | 0.491 s | 0.515 s | +0.010 s | -0.222 to +0.465 s | +2.63% | 3/6 |
| Ruff, Original edit 1 | 8.855 s | 8.601 s | -0.598 s | -1.355 to +0.478 s | -6.66% | 2/6 |
| Ruff, Original edit 2 | 9.670 s | 9.409 s | -0.334 s | -0.844 to +0.545 s | -3.46% | 1/6 |
| Ruff, Original edit 3 | 10.835 s | 10.668 s | -0.186 s | -0.418 to +0.436 s | -1.72% | 2/6 |
| Uv, Cold check | 49.015 s | 48.674 s | -0.054 s | -1.344 to +0.627 s | -0.13% | 3/6 |
| Uv, Warm no-op | 0.761 s | 0.722 s | +0.091 s | -0.483 to +0.592 s | +12.32% | 4/6 |
| Uv, Original edit 1 | 5.037 s | 4.969 s | -0.033 s | -0.951 to +0.686 s | -0.66% | 3/6 |
| Uv, Original edit 2 | 1.722 s | 1.513 s | +0.023 s | -0.353 to +0.226 s | +1.37% | 4/6 |
| Uv, Original edit 3 | 4.700 s | 4.654 s | +0.068 s | -0.786 to +0.283 s | +1.53% | 4/6 |

Ruff generally runs faster without sparse metadata in these samples, including a paired median 0.875 s cold improvement and 0.598 s first-edit improvement. The corresponding ranges include slower removal samples. uv paired medians vary from a 54 ms cold improvement to a 91 ms no-op loss. These data do not support treating sparse metadata as an established elapsed-time improvement.

| Project and state | Median paired maximum-child RSS delta | Paired range | Increased pairs |
| --- | ---: | ---: | ---: |
| Ruff, Cold check | +34.05 MiB | +4.61 to +39.54 MiB | 6/6 |
| Ruff, Warm no-op | +0.05 MiB | -0.36 to +0.23 MiB | 3/6 |
| Ruff, Original edit 1 | +16.46 MiB | +12.32 to +23.43 MiB | 6/6 |
| Ruff, Original edit 2 | +40.13 MiB | +2.92 to +52.60 MiB | 6/6 |
| Ruff, Original edit 3 | +17.15 MiB | -7.80 to +27.20 MiB | 5/6 |
| Uv, Cold check | +29.01 MiB | +22.39 to +41.11 MiB | 6/6 |
| Uv, Warm no-op | -0.06 MiB | -0.37 to +0.25 MiB | 3/6 |
| Uv, Original edit 1 | +26.50 MiB | +14.71 to +42.44 MiB | 6/6 |
| Uv, Original edit 2 | +16.57 MiB | +9.41 to +36.29 MiB | 6/6 |
| Uv, Original edit 3 | +31.88 MiB | +25.13 to +36.05 MiB | 6/6 |

Removing the feature raises this memory metric in every pair for Ruff cold, first edit and second edit, and for uv cold and all three edits. It does not measure aggregate memory across simultaneous compiler processes. No platform-wide or whole-pipeline peak claim follows from this maximum-child metric.

The complete historical archive has 1,234 payloads and 1,235 safe regular members, preserving all eighteen Ruff/uv attempts (twelve accepted and six excluded). Historical Dense launch/config/status records, including old isolated Codex launch metadata, remain present; old Codex timing payloads are not pooled. The independent root command audit rechecked 120 checks, ten statistics, 1,537 continuous and 144 required quiet samples. Its proof audit rehashed 59 bodies, both 69,859-file maps, fourteen own loader records and source/profile/native evidence. The only optimizer-policy normalization is the accepted build-jobs 24-versus-12 setting. Both arms retain matched original eleven-command training inputs and own PGO/BOLT.

[Original Ruff/uv command audit](dense-original-twelve-command-root-review-01.json), [original proof audit](dense-original-twelve-proof-root-review-01.json), [all historical raw payloads](original-twelve-raw-retrieved-ssh-01/packet/validation/dense-original-twelve-ruff-uv-complete-01/packet.json), [current OpenAI2 final release](../next-fleet-plans-01/ordinary-semantic-plan-01/final-archive-readers-current-release-actual-ssh-03/decoded.json) and [paired-statistic recomputation](dense-all-project-paired-statistics-self-review-01.json) preserve the exact bindings.

The frozen Ruff/uv schedule is `eceb8306c768de9698a6a42b5705299df02d6a8b35b5824f11bd7f98acaa8864`; the new Codex schedule is `47664852a3b7894f41753460d5195d508cf39df270dd74e29e0f3b9dcc717c6e`. A coherent combined lean-stack comparison remains necessary after individual decisions; marginal effects from different candidates cannot be added.
