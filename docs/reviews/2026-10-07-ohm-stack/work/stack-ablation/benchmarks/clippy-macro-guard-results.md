# Clippy macro guard #44: representative command screen

**Retain the two guards provisionally and prefer upstreaming them.** Removing eight lines adds about 0.96 s to Codex's cold command and 0.19 s after its direct edit; both pairs are slower in those states. Ruff's direct edit loses about 75 ms in both pairs, while other Ruff/uv states are small or mixed. Those small gains still need scrutiny. The implementation is two early exits with no new cache, schema or retained state, so this screen offers less reason to remove it than the larger mechanisms under review.

The reduced arm removes only the two effective-`Allow` guards added in Clippy #44 to `clippy_lints/src/nonstandard_macro_braces.rs`. The guard skips macro-brace analysis when the effective lint level permits it. Removing it makes the lint do that analysis again. The frozen source delta is exactly one file, zero added lines and eight removed lines; all compiler/Cargo bytes and optimization policy are shared. Each Clippy source arm retained its own accepted PGO profile and the same training inputs. This is the source-removal result under the stack's ordinary optimized build policy, including its source-dependent PGO, rather than an unprofiled microbenchmark.

Each project ran two counterbalanced pairs on `charlie-oss-0` (32 CPUs, eight Cargo jobs): slot 0 ran full then reduced, and slot 1 ran reduced then full. Each arm used an independent empty history and the original four Clippy commands: cold, warm no-op, after the recorded direct edit, and after an API-stable dependency edit. Ruff selected the ty semantic/core packages, uv selected `uv-pypi-types`/`uv-client`, and Codex selected `codex-tui`. The original `--all-targets`/`--tests` and lint policies were preserved. These targets were linted and compiled as needed; **zero project tests were executed**.

The direct edits were the original recursive-attribute-inference change in Ruff, PyPI Simple API JSON parser change in uv, and active-cell transcript layout change in Codex. Compatibility patches and all source/lockfile phases were identical between arms. Registry downloads and source preparation preceded timing. Warm-up compilation was disabled. Ohm shared-build behavior remained enabled under the existing per-history isolation.

Positive paired deltas mean the reduced arm was slower. Percentages are the medians of the two individual paired percentages. There are only two pairs per project: this is screening evidence, with no confidence intervals or significance claim. Every retained accepted cell is shown; no outlier was removed.

| Project | Command state | Guard median (s) | Removed median (s) | Paired median delta (ms) | Individual paired deltas (ms) | Paired median (%) | Removal slower |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| Ruff | cold | 31.608 | 31.607 | -0.5 | -346.6, +345.5 | +0.00 | 1/2 |
| Ruff | noop | 0.482 | 0.470 | -11.6 | -51.7, +28.5 | -1.82 | 1/2 |
| Ruff | direct | 11.883 | 11.958 | +74.9 | +19.7, +130.1 | +0.63 | 2/2 |
| Ruff | dependency | 0.989 | 0.998 | +9.0 | +11.3, +6.7 | +0.91 | 2/2 |
| uv | cold | 38.499 | 38.482 | -16.7 | +270.2, -303.6 | -0.04 | 1/2 |
| uv | noop | 0.699 | 0.669 | -29.9 | +27.1, -86.9 | -3.46 | 1/2 |
| uv | direct | 4.737 | 4.735 | -1.9 | -17.1, +13.4 | -0.04 | 1/2 |
| uv | dependency | 0.867 | 0.849 | -17.5 | -12.5, -22.4 | -2.00 | 0/2 |
| Codex | cold | 127.005 | 127.964 | +958.5 | +1590.4, +326.7 | +0.76 | 2/2 |
| Codex | noop | 1.667 | 1.665 | -1.9 | -20.7, +16.8 | -0.09 | 1/2 |
| Codex | direct | 20.118 | 20.310 | +191.3 | +86.3, +296.3 | +0.95 | 2/2 |
| Codex | dependency | 2.269 | 2.305 | +36.6 | +47.5, +25.7 | +1.61 | 2/2 |

History totals are secondary context: they add the four timed commands, excluding edits, preparation and quiet waits. They do not estimate the frequency of cold or edited commands in practice.

| Project | Slot 0 total delta (s / %) | Slot 1 total delta (s / %) |
| --- | ---: | ---: |
| Ruff | -0.367 / -0.81% | +0.511 / +1.14% |
| uv | +0.268 / +0.60% | -0.400 / -0.88% |
| Codex | +1.703 / +1.13% | +0.665 / +0.44% |

The 48 accepted commands total 16.095 minutes of elapsed command time. Installation, native validation, component builds, prefetch, quiet waits and rejected attempts are outside that number. It is not a supervisor or end-to-end campaign duration.

## Complexity and correctness

The proposed simplification removes eight lines and restores unconditional lint analysis. It does not delete module-cache machinery or the separate MSRV shortcut, and this comparison says nothing about those features. Keep the guard provisional because most measured differences are small; upstreaming the two early exits would preserve their useful behavior while reducing the fork delta.

The accepted native evidence retained 25 component tests and the original two-check control UI result. Supplemental validation ran 16 driver calls forming eight diagnostic/metadata arm pairs, including swapped macro locations, nested `allow`/`warn`/`expect` behavior and four warm loads. Those checks passed; the ordinary timing did not rerun them or execute a project suite. This supports the bounded diagnostic contract, not universal semantic equivalence.

## Accepted scope and provenance

All six pairs, 48 commands, 12 command statistics, 1,098 continuous monitor samples and 96 required quiet samples passed root review. The final audit rehashed every archived payload and original tar mode, every readiness proof, both complete 69,859-file runtime maps and their own current size/modes, all seven tools under both loader environments, source/PGO/native bindings and terminal ownership release. The 69,857 noncomponent files are byte-identical between arms. No build, training or native suite was repeated for the timing host.

All six timed positions passed on attempt 1. Earlier untimed preparation and archival caller failures are preserved separately and contribute no timed samples.

Raw log hashes, source/lockfile equality and successful statuses were verified. The report does not claim exact rendered warning-text equivalence, full-project coverage or combined-stack performance. All changes discussed here remain recommendations; this screen has not removed or landed a stack change.

The original commands, with the full selector shown, were:

```text
Ruff: cargo +ohm-ablation-clippy-full clippy -p ty_python_semantic -p ty_python_core --all-targets -- -D warnings -A clippy::format_push_string -A clippy::double_must_use -A clippy::assert_is_empty -A clippy::needless_borrows_for_generic_args -A clippy::mut_mut
uv: cargo +ohm-ablation-clippy-full clippy -p uv-pypi-types -p uv-client --all-targets --locked -- -D warnings -A clippy::doc_markdown -A clippy::double_must_use
Codex: cargo +ohm-ablation-clippy-full clippy --tests -p codex-tui -- -D clippy::redundant_closure_for_method_calls
```

Frozen project revisions: Ruff `21c9b077ab3b10dd9007710ffa471cd12f7eceab`, uv `a50af60fb4162d7f94812d64c481c30a0200b6d8`, Codex `74004b5397b24662a87a5264a6ae80664168c7f3`. Boot ID `68db8bb3-5bac-4c42-8902-017b488cf59a`.

[All machine-readable command cells](clippy-original-builder-reassessment-01/macro-report-statistics-recomputation-01.json) · [Root command audit](clippy-original-builder-reassessment-01/macro-complete-command-root-review-01.json) · [Final root acceptance](clippy-original-builder-reassessment-01/macro-complete-root-review-01.json) · [Immutable raw manifest](clippy-original-builder-reassessment-01/macro-capture-complete-03/packet/validation/clippy-macro-complete-03/packet.json)

Raw archive SHA-256 `0a9b08c91b8bc4729d6d895066ce67643d089941c44a41ef634226849d6803b8`; 92,060,526 bytes, 633 regular members and 632 payloads. Final root receipt SHA-256 `247d1e9b0a981853a63d45e3f033085c0ec29ddfdfbf84c54b1b919569ed0a7c`.

[Exact eight-line source removal](../clippy/no-macro-guard.patch) · [Native supplemental root review](../clippy/no-macro-guard-build-draft/supplemental-native-03/final-capture-01/root-review.json)
