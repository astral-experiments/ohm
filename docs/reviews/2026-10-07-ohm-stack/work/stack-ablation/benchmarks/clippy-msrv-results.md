# Clippy MSRV shortcut #46: representative command screen

**Remove the six-line shortcut for upstream parity, accepting the measured costs.** The shortcut produces useful savings in some commands, so its removal is a tradeoff. Codex's direct-edit command becomes 1.658 s slower (+5.87%), Ruff's direct edit becomes 0.391 s slower (+1.96%), and uv's no-op becomes 0.374 s slower (+54.04%). Both orders are slower in those states. Removal improves both Ruff cold commands and both Ruff/uv dependency-edit commands; several other states change direction between the two orders. Given the goal of reducing fork-specific changes, this mixed screen supports accepting the losses for a small reduction in the fork. It does not show that the shortcut has no effect.

The treatment reverses only [Clippy #46](https://github.com/astral-sh/ohm-rust-clippy/pull/46): the comment and `if attrs.is_empty() { return None; }` in `clippy_utils/src/msrvs.rs`. The existing iterator returns `None` for that empty slice. The [exact patch](../clippy/no-msrv-shortcut.patch) deletes six lines in one file, adding none; it introduces no replacement state. This is a modest simplification, with no cache, schema or API removal. Module-cache reuse, the macro guard and clone analysis have separate ablations and remain outside this source boundary.

Both arms use the same compiler and Cargo. Exactly the two Clippy binaries differ in the complete 69,859-file runtimes. Each source arm uses its own accepted PGO profile under the same release codegen policy and training inputs. The results therefore describe removing the shortcut under the normal optimized build policy, including source-dependent PGO. They cannot isolate the early return's instruction cost from the resulting profile and code layout.

Ruff and uv ran on `charlie-serc-841-cell-5` (32 CPUs); Codex ran prospectively on `charlie-openai-2` (16 CPUs) after the Cell5 Codex attempt was rejected before timing. Each project has two counterbalanced pairs on one host: slot 0 ran shortcut→removed, and slot 1 ran removed→shortcut. No project combines timing samples from different hosts. Eight Cargo jobs and the original four Clippy commands were retained: cold, warm no-op, the recorded direct edit, and an API-stable dependency edit. Each arm began with its own empty target/shared history. Warm-up compilation was disabled; source preparation, registry fetching, edits, quiet waits and correctness validation were outside the command timers.

Ruff selected the ty semantic/core packages, uv selected `uv-pypi-types`/`uv-client`, and Codex selected `codex-tui`. The original `--all-targets`/`--tests` and lint policies were preserved. The direct edits were recursive attribute inference in Ruff, the PyPI Simple API JSON parser in uv, and active-cell transcript layout in Codex. These commands compiled and linted their selected targets; **zero project tests were executed**.

All deltas are **removed minus shortcut**. Negative values favor removal. Percentages are calculated within each pair and then summarized, so the percentage median need not equal the ratio of arm medians. The observed range covers only two pairs and is not a confidence interval. Every accepted cell remains visible; no outlier was removed.

| Project | State | Shortcut median (s) | Removed median (s) | Paired delta (s) | Paired delta (%) | Observed delta range (s) | Slower after removal |
|---|---|---:|---:|---:|---:|---:|---:|
| ruff | Cold | 53.139 | 50.879 | -2.261 | -4.14% | -3.700 to -0.821 | 0/2 |
| ruff | Warm no-op | 0.575 | 0.680 | +0.105 | +18.63% | +0.090 to +0.120 | 2/2 |
| ruff | Direct edit | 20.111 | 20.502 | +0.391 | +1.96% | +0.057 to +0.726 | 2/2 |
| ruff | Dependency edit | 1.653 | 1.454 | -0.200 | -11.51% | -0.327 to -0.072 | 0/2 |
| uv | Cold | 59.048 | 59.811 | +0.763 | +1.29% | +0.701 to +0.824 | 2/2 |
| uv | Warm no-op | 0.696 | 1.070 | +0.374 | +54.04% | +0.285 to +0.463 | 2/2 |
| uv | Direct edit | 7.091 | 6.932 | -0.159 | -2.24% | -0.351 to +0.033 | 1/2 |
| uv | Dependency edit | 1.232 | 0.987 | -0.246 | -19.80% | -0.289 to -0.203 | 0/2 |
| codex | Cold | 174.252 | 175.799 | +1.547 | +0.92% | -2.722 to +5.817 | 1/2 |
| codex | Warm no-op | 2.901 | 2.713 | -0.188 | -5.52% | -0.648 to +0.272 | 1/2 |
| codex | Direct edit | 29.954 | 31.612 | +1.658 | +5.87% | +0.027 to +3.290 | 2/2 |
| codex | Dependency edit | 3.649 | 3.445 | -0.203 | -5.28% | -0.414 to +0.007 | 1/2 |

The largest repeated loss is Codex's direct edit, but its two costs differ substantially: +3.290 s in slot 0 and +0.027 s in slot 1. That range limits any claim about the usual cost. Ruff direct and both Ruff/uv no-op commands repeatedly slow after removal. uv cold also repeatedly slows, by 0.701–0.824 s. Ruff cold repeatedly improves, by 0.821–3.700 s. The faster Ruff/uv dependency edits are small in absolute time (0.072–0.327 s and 0.203–0.289 s). Codex cold, no-op and dependency edit are mixed, as is uv's direct edit. Large no-op percentages reflect short commands and should be read alongside their absolute times.

The two orders are shown separately below. Their variation is part of the result, including the near-zero Codex direct cost in slot 1.

| Project | State | Slot 0 delta (s / %) | Slot 1 delta (s / %) |
|---|---|---:|---:|
| ruff | Cold | -3.700 / -6.67% | -0.821 / -1.62% |
| ruff | Warm no-op | +0.090 / +14.21% | +0.120 / +23.05% |
| ruff | Direct edit | +0.057 / +0.28% | +0.726 / +3.64% |
| ruff | Dependency edit | -0.327 / -18.25% | -0.072 / -4.76% |
| uv | Cold | +0.824 / +1.41% | +0.701 / +1.18% |
| uv | Warm no-op | +0.463 / +68.15% | +0.285 / +39.93% |
| uv | Direct edit | -0.351 / -4.95% | +0.033 / +0.46% |
| uv | Dependency edit | -0.289 / -22.12% | -0.203 / -17.48% |
| codex | Cold | -2.722 / -1.55% | +5.817 / +3.38% |
| codex | Warm no-op | +0.272 / +10.00% | -0.648 / -21.04% |
| codex | Direct edit | +3.290 / +11.65% | +0.027 / +0.08% |
| codex | Dependency edit | -0.414 / -10.76% | +0.007 / +0.20% |

The memory observations do not establish a general benefit from either choice. GNU time records maximum child RSS per command, shown in MiB below as the median and two-pair range. This is not the combined peak or sum of all parallel compiler processes. Most paired differences are small; uv cold uses less memory after removal while some Codex commands use more.

| Project | State | Shortcut RSS median [range] (MiB) | Removed RSS median [range] (MiB) | Paired RSS delta median [range] (MiB) |
|---|---|---:|---:|---:|
| ruff | Cold | 1764.3 [1762.7–1766.0] | 1760.6 [1749.5–1771.8] | -3.7 [-13.2–+5.8] |
| ruff | Warm no-op | 64.5 [64.4–64.6] | 64.5 [64.4–64.6] | +0.0 [+0.0–+0.0] |
| ruff | Direct edit | 1445.8 [1442.8–1448.7] | 1443.4 [1438.9–1447.9] | -2.3 [-3.9–-0.8] |
| ruff | Dependency edit | 334.0 [333.8–334.3] | 334.0 [333.7–334.4] | +0.0 [-0.6–+0.6] |
| uv | Cold | 625.3 [623.2–627.3] | 612.0 [609.0–615.0] | -13.3 [-14.2–-12.3] |
| uv | Warm no-op | 93.0 [92.9–93.1] | 92.9 [92.9–92.9] | -0.1 [-0.3–+0.0] |
| uv | Direct edit | 596.0 [595.8–596.2] | 597.2 [596.6–597.8] | +1.3 [+0.4–+2.1] |
| uv | Dependency edit | 183.0 [182.8–183.2] | 183.1 [182.9–183.3] | +0.1 [+0.1–+0.1] |
| codex | Cold | 3009.3 [3009.2–3009.4] | 3015.0 [2996.8–3033.2] | +5.7 [-12.6–+24.0] |
| codex | Warm no-op | 188.0 [188.0–188.1] | 188.6 [188.6–188.7] | +0.6 [+0.5–+0.6] |
| codex | Direct edit | 3521.2 [3518.4–3524.0] | 3530.0 [3525.6–3534.4] | +8.8 [+1.6–+16.0] |
| codex | Dependency edit | 265.6 [265.6–265.7] | 266.0 [265.9–266.1] | +0.4 [+0.2–+0.6] |

Adding the four command timers gives secondary history context. These sums exclude preparation, edits and quiet waits and do not model real command frequency. They also do not replace the individual regressions above.

| Project | Slot 0 total delta (s / %) | Slot 1 total delta (s / %) |
|---|---:|---:|
| ruff | -3.881 / -4.96% | -0.047 / -0.07% |
| uv | +0.648 / +0.96% | +0.816 / +1.19% |
| codex | +0.426 / +0.20% | +5.203 / +2.47% |

The 48 accepted commands total 23.673 minutes of elapsed command time. That excludes component builds, installation, training, native validation, prefetch, quiet waits and rejected attempts; it is not end-to-end campaign duration.

The original component instrument/train/use/native phases took 234.3/103.0/219.3/175.1 seconds, including verification and export-copy work. Those setup costs are not shortcut latency measurements. The exported Clippy binaries total 16,986,312 bytes, 4,328 bytes smaller after removal; that size difference alone is not a performance benefit.

The [source contract](../component-build/receipts/clippy-no-msrv-shortcut/source-contract/msrv-source-scope.json) verifies the single-file six-line delta against all 4,604 source files and modes, including the unchanged MSRV-stack callbacks. The frozen compiler calls the early attribute callbacks even for empty slices, so the shortcut addresses a reachable path. This screen does not count how often the branch executed in these commands. The accepted training closure contains 1,790 files and the same three executed collector commands over nine crates. Original native evidence includes 23 component tests with none ignored, plus 18 diagnostic/metadata history comparisons covering 62 positive lint IDs and four loaded-state assertion calls across the two arms. Those bounded checks passed and were reused on the timing hosts; no build, training or native suite was repeated for migration.

All six accepted positions passed on their fixed first timing attempt. Ruff slot 0 had an earlier launcher import failure before any timed command; its exact retained launch was recovered without reusing partial timers. The original Cell5 Codex attempt was rejected before timing because of foreign compiler activity. Its failed record remains archived and contributes no sample. Codex's two accepted comparisons come entirely from the new OpenAI2 block. Earlier setup and transport failures remain preserved separately.

The final independent root review accepts six pairs, 48 commands and twelve states, 1,178 continuous-monitor samples and 96 quiet samples. It rehashed all 129 readiness proofs across both host blocks, original archive payloads and tar modes, own complete runtime maps and loading graphs, source/PGO/native identities, and final collector/reader ownership closures. Raw command logs, successful statuses and source/lockfile parity passed. Exact rendered warning-text equality, full-project coverage and combined-stack performance are not claimed. The two-pair screen supports a deliberate upstream-parity choice; it does not establish statistical significance or a universal absence of benefit. The recommendation has not itself removed or landed a stack change.

Original commands, with each block's full selector shown:

```text
Ruff: cargo +ohm-ablation-clippy-full clippy -p ty_python_semantic -p ty_python_core --all-targets -- -D warnings -A clippy::format_push_string -A clippy::double_must_use -A clippy::assert_is_empty -A clippy::needless_borrows_for_generic_args -A clippy::mut_mut
uv: cargo +ohm-ablation-clippy-full clippy -p uv-pypi-types -p uv-client --all-targets --locked -- -D warnings -A clippy::doc_markdown -A clippy::double_must_use
Codex: cargo +ohm-ablation-clippy-msrv-codex-full clippy --tests -p codex-tui -- -D clippy::redundant_closure_for_method_calls
```

Frozen revisions: Ruff `21c9b077ab3b10dd9007710ffa471cd12f7eceab`, uv `a50af60fb4162d7f94812d64c481c30a0200b6d8`, Codex `74004b5397b24662a87a5264a6ae80664168c7f3`. Cell5 boot `5281ce3e-c918-4ac3-8916-600d84d3e69f`; OpenAI2 boot `1d2b2173-306c-47a6-8070-310db540c8af`.

[Final independent root acceptance](clippy-msrv-cell5-preparation-plan-01/msrv-final-root-review-01.json) · [Every command/RSS cell and recomputation](clippy-msrv-cell5-preparation-plan-01/msrv-report-statistics-recomputation-01.json) · [Ruff/uv root command review](clippy-msrv-cell5-preparation-plan-01/msrv-retained-four-command-root-review-01.json) · [Codex root command review](clippy-msrv-cell5-preparation-plan-01/codex-only-openai2-migration-01/msrv-codex-two-command-root-review-01.json)

The final root receipt has SHA256 `fea2cd7df4b506444303e0359620223280fbf502838c45db915029c13ef61761`. The [Ruff/uv raw archive](clippy-msrv-cell5-preparation-plan-01/retained-four-raw-retrieved-ssh-01/raw.tar.gz.not-included.md) has SHA256 `16ee30ae30f30555c947e264e26f612be57680da9d0aca305f8632fe11887b28`, 80,916,507 bytes and 437 regular members/436 payloads. The [Codex raw archive](clippy-msrv-cell5-preparation-plan-01/codex-only-openai2-migration-01/two-codex-raw-retrieved-ssh-01/raw.tar.gz.not-included.md) has SHA256 `c882b38457e04c3f93c114369c4da8caf876d63e9621a9030577005f287daf87`, 120,921,584 bytes and 303 regular members/302 payloads.
