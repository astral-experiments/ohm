# Clippy PGO: representative command screen

**Retain Clippy PGO provisionally.** Removing it repeatedly costs Ruff about 1.38 s cold and 0.79 s after the direct edit, and Codex about 3.00 s cold and 1.15 s after its direct edit. uv also loses about 0.25 s after its direct edit, although its cold result is mixed. These are useful command gains, but the extra instrumentation and training consume 335.33 s of recorded release work. The screen supports keeping that work for these commands; it does not establish its value across all Clippy workloads or a developer's day.

This comparison isolates the Clippy portion of Rust #67. Both arms have exactly the same Clippy source, compiler, Cargo, rustdoc and other tool binaries. The reduced arm removes only Clippy component PGO. The accepted resolved codegen policy compares equal after excluding the own profile-use option and its two PGO helper LLVM flags. No Clippy lint optimization was removed.

Each project ran two counterbalanced pairs on `charlie-oss-0` (32 CPUs, eight Cargo jobs): slot 0 ran full then reduced, and slot 1 ran reduced then full. Each arm used an independent empty history and the original four Clippy commands: cold, warm no-op, after the recorded direct edit, and after an API-stable dependency edit. Ruff selected the ty semantic/core packages, uv selected `uv-pypi-types`/`uv-client`, and Codex selected `codex-tui`. The original `--all-targets`/`--tests` and lint policies were preserved. These targets were linted and compiled as needed; **zero project tests were executed**.

The direct edits were the original recursive-attribute-inference change in Ruff, PyPI Simple API JSON parser change in uv, and active-cell transcript layout change in Codex. Compatibility patches and all source/lockfile phases were identical between arms. Registry downloads and source preparation preceded timing. Warm-up compilation was disabled. Ohm shared-build behavior remained enabled under the existing per-history isolation.

Positive paired deltas mean the reduced arm was slower. Percentages are the medians of the two individual paired percentages. There are only two pairs per project: this is screening evidence, with no confidence intervals or significance claim. Every retained accepted cell is shown; no outlier was removed.

| Project | Command state | PGO median (s) | PGO-OFF median (s) | Paired median delta (ms) | Individual paired deltas (ms) | Paired median (%) | OFF slower |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| Ruff | cold | 31.349 | 32.725 | +1375.9 | +1424.7, +1327.1 | +4.39 | 2/2 |
| Ruff | noop | 0.439 | 0.530 | +91.5 | +92.4, +90.6 | +20.86 | 2/2 |
| Ruff | direct | 11.966 | 12.756 | +790.7 | +815.9, +765.4 | +6.61 | 2/2 |
| Ruff | dependency | 1.039 | 1.134 | +94.3 | +113.3, +75.3 | +9.11 | 2/2 |
| uv | cold | 38.062 | 38.357 | +294.8 | +655.6, -65.9 | +0.78 | 1/2 |
| uv | noop | 0.700 | 0.690 | -10.5 | -64.0, +42.9 | -1.07 | 1/2 |
| uv | direct | 4.782 | 5.032 | +249.9 | +228.6, +271.2 | +5.23 | 2/2 |
| uv | dependency | 0.919 | 0.902 | -16.9 | -101.2, +67.3 | -1.02 | 1/2 |
| Codex | cold | 128.893 | 131.889 | +2995.8 | +3963.4, +2028.1 | +2.32 | 2/2 |
| Codex | noop | 1.748 | 1.729 | -19.9 | +1.0, -40.7 | -1.13 | 1/2 |
| Codex | direct | 20.606 | 21.760 | +1153.4 | +1081.5, +1225.3 | +5.60 | 2/2 |
| Codex | dependency | 2.423 | 2.351 | -72.3 | -144.3, -0.4 | -3.02 | 0/2 |

History totals are secondary context: they add the four timed commands, excluding edits, preparation and quiet waits. They do not estimate the frequency of cold or edited commands in practice.

| Project | Slot 0 total delta (s / %) | Slot 1 total delta (s / %) |
| --- | ---: | ---: |
| Ruff | +2.446 / +5.47% | +2.258 / +5.03% |
| uv | +0.719 / +1.62% | +0.315 / +0.71% |
| Codex | +4.902 / +3.19% | +3.212 / +2.09% |

The 48 accepted commands total 16.426 minutes of elapsed command time. Installation, native validation, component builds, prefetch, quiet waits and rejected attempts are outside that number. It is not a supervisor or end-to-end campaign duration.

## Build cost and complexity

PGO adds an instrumented build, training/profile collection and merge, and profile-use compilation of the Clippy component. The retained run recorded 233.29 s for instrumentation and 102.04 s for training: 335.33 s in additional phases. This creates profile/corpus and release-pipeline work even though the lint source is identical. The other recorded phases are listed for accounting; they are single runs with verification/export work and unequal validation durations, so their differences are not counterbalanced build-speed measurements.

| Arm | Phase | Elapsed (s) | User CPU (s) | System CPU (s) | Max child RSS (KiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| PGO | instrument | 233.29 | 361.38 | 42.39 | 2062020 |
| PGO | train | 102.04 | 468.41 | 156.39 | 1019272 |
| PGO | use | 219.28 | 242.00 | 41.20 | 2060388 |
| PGO | test | 67.03 | 48.85 | 19.09 | 437248 |
| PGO-OFF | use | 211.24 | 229.64 | 39.74 | 2052780 |
| PGO-OFF | test | 180.11 | 175.95 | 27.59 | 2026044 |

The OFF `clippy-driver`/`cargo-clippy` pair is 222,704 bytes larger. Binary size and maximum child RSS are separate from latency; child RSS is not simultaneous aggregate memory. There is no break-even estimate here because the screen does not measure command frequency or release cadence. The few-second cold/direct savings support retaining PGO provisionally, while leaving the release-work tradeoff explicit.

## Accepted scope and provenance

All six pairs, 48 commands, 12 command statistics, 1,033 continuous monitor samples and 96 required quiet samples passed root review. The final audit rehashed every archived payload and original tar mode, every readiness proof, both complete 69,859-file runtime maps and their own current size/modes, all seven tools under both loader environments, source/PGO/native bindings and terminal ownership release. The 69,857 noncomponent files are byte-identical between arms. No build, training or native suite was repeated for the timing host.

Ruff slot 1 attempt 1 was rejected before any timed command after a foreign Cargo process appeared during the initial quiet gate. Its raw rejection and release remain archived; the same frozen slot was rerun once and attempt 2 passed. The other five accepted positions used attempt 1. No partial or rejected commands enter these statistics.

Raw log hashes, source/lockfile equality and successful statuses were verified. The report does not claim exact rendered warning-text equivalence, full-project coverage or combined-stack performance. All changes discussed here remain recommendations; this screen has not removed or landed a stack change.

The original commands, with the full selector shown, were:

```text
Ruff: cargo +ohm-ablation-clippy-full clippy -p ty_python_semantic -p ty_python_core --all-targets -- -D warnings -A clippy::format_push_string -A clippy::double_must_use -A clippy::assert_is_empty -A clippy::needless_borrows_for_generic_args -A clippy::mut_mut
uv: cargo +ohm-ablation-clippy-full clippy -p uv-pypi-types -p uv-client --all-targets --locked -- -D warnings -A clippy::doc_markdown -A clippy::double_must_use
Codex: cargo +ohm-ablation-clippy-full clippy --tests -p codex-tui -- -D clippy::redundant_closure_for_method_calls
```

Frozen project revisions: Ruff `21c9b077ab3b10dd9007710ffa471cd12f7eceab`, uv `a50af60fb4162d7f94812d64c481c30a0200b6d8`, Codex `74004b5397b24662a87a5264a6ae80664168c7f3`. Boot ID `68db8bb3-5bac-4c42-8902-017b488cf59a`.

[All machine-readable command cells](clippy-original-builder-reassessment-01/pgo-off-report-statistics-recomputation-01.json) · [Root command audit](clippy-original-builder-reassessment-01/pgo-off-complete-command-root-review-01.json) · [Final root acceptance](clippy-original-builder-reassessment-01/pgo-off-complete-root-review-01.json) · [Immutable raw manifest](clippy-original-builder-reassessment-01/pgo-off-capture-complete-03/packet/validation/clippy-pgo-off-complete-03/packet.json)

Raw archive SHA-256 `27b137957c0eaf6e1a6870b32ab7d43a61c34a5debb413f1a8602a61e770e14e`; 98,301,788 bytes, 644 regular members and 643 payloads. Final root receipt SHA-256 `b6da18aaf43b10b93d8a0748fd00e86a0531e3e013fe917b68721fe9ad750b27`.

[Resolved optimization/source policy](../component-build/receipts/clippy-pgo-off-resolved-optimization-policy.json) · [Recorded build costs](../component-build/receipts/clippy-pgo-off-build-cost.json)
