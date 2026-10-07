# Workspace resolver cache: representative command screen

**Retain provisionally.** The screen found useful savings on several real edits, but the benefit is uneven. Removing the cache added about 1.09 s to the first Ruff edit and 0.51–0.55 s to the second and third uv edits. Both pairs were slower in those states. Cold uv/Codex checks and Ruff no-op checks favored removal. The cache adds 237 lines of input tracking; the measured benefit does not justify every part of that contract by itself.

The same accepted optimized compiler/Cargo runtime was used in both arms. The reduced arm set `CARGO_EXPERIMENTAL_RESOLVE_CACHE=0`; all other Ohm defaults stayed enabled. On `charlie-oss-2`, each project ran two opposite-order pairs with independent empty histories, eight jobs, and five original selected-library `cargo check --locked --offline --lib` commands: cold, no-op, and the three recorded edits. No project test suite ran. Ruff selected `ty_python_semantic`/`ty_python_core`; the original uv and Codex recipes and compatibility patches were preserved.

Positive deltas mean removing the cache was slower. These are the full two-pair results, with no outlier selection, confidence intervals, or statistical significance claims.

| Project | Command | Cache median (s) | Cache OFF median (s) | Paired median delta (ms) | Individual paired deltas (ms) | OFF slower |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| ruff | cold-check | 29.473 | 30.658 | +1185.8 | -187.6, +2559.1 | 1/2 |
| ruff | warm-noop-check | 1.080 | 0.969 | -111.3 | -81.4, -141.2 | 0/2 |
| ruff | original-edit-1-check | 9.356 | 10.446 | +1089.4 | +1162.3, +1016.5 | 2/2 |
| ruff | original-edit-2-check | 10.777 | 10.573 | -204.4 | +247.8, -656.7 | 1/2 |
| ruff | original-edit-3-check | 11.459 | 11.429 | -30.2 | -217.7, +157.4 | 1/2 |
| uv | cold-check | 53.277 | 52.205 | -1072.7 | -2101.1, -44.3 | 0/2 |
| uv | warm-noop-check | 0.785 | 0.942 | +157.1 | +270.8, +43.5 | 2/2 |
| uv | original-edit-1-check | 5.296 | 5.385 | +89.0 | +57.5, +120.5 | 2/2 |
| uv | original-edit-2-check | 1.650 | 2.156 | +505.6 | +537.5, +473.6 | 2/2 |
| uv | original-edit-3-check | 4.896 | 5.446 | +549.6 | +608.3, +491.0 | 2/2 |
| codex | cold-check | 155.473 | 153.201 | -2271.9 | -2763.9, -1779.9 | 0/2 |
| codex | warm-noop-check | 2.686 | 3.370 | +684.2 | +1983.8, -615.5 | 1/2 |
| codex | original-edit-1-check | 9.886 | 10.321 | +434.8 | +50.2, +819.4 | 2/2 |
| codex | original-edit-2-check | 7.623 | 8.165 | +542.3 | -13.7, +1098.3 | 1/2 |
| codex | original-edit-3-check | 7.534 | 7.841 | +307.4 | +1186.6, -571.8 | 1/2 |

All six pairs, 60 timed commands, 15 command statistics, 1,108 continuous monitor samples and 96 required quiet samples passed independent root review. Every source and lockfile phase, command status, raw log hash, original readiness binding, complete runtime map and terminal ownership release was checked. Earlier native validation retained 12 contracts and 12 actual cold/warm checks, including enabled-side cache reuse and disabled-side absence. Native validation, build and training work was reused.

Unsuccessful untimed quiet windows remain in the raw packet; each final window passed all six original intervals. The accepted method requires post-cleanup quiet after deleting at least 1 GiB; all four required post-cleanup windows passed. No failed timed pair or historical sample was imported.

The third uv edit changes test compatibility code and may be inactive for a selected library check. RSS records are maximum child-process RSS, not simultaneous aggregate memory; recorded disk use is an endpoint, not peak storage. Log hashes and successful statuses were verified; this report does not claim exact rendered warning-text equivalence. The results apply to these selected commands, not every workflow or the complete simplified stack.

[Machine-readable statistics](resolver-inplace-screen-01/independent-complete-results-review.json) · [Root acceptance](resolver-inplace-screen-01/resolver-complete-root-review.json) · [Raw packet manifest](resolver-inplace-screen-01/capture-complete-01/packet/validation/resolver-complete-01/packet.json)
