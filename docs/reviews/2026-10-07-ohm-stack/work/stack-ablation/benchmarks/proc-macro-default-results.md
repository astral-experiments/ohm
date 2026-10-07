# Proc-macro cache default

Hold the blanket default-off change. Disabling the cache improves Codex’s cold check and all three edited checks in both pairs, but costs Ruff a paired median 2.09 seconds after its second edit and 0.70 seconds after its third. Both Ruff pairs agree in those two edited states. uv has small, mixed effects. The complete screen establishes a workload tradeoff; its two pairs per project do not establish a general winner.

This expansion cache is upstream Rust code. Changing Ohm’s automatic default removes no compiler fork implementation. It is also separate from Cargo’s registry macro artifact reuse and trusted local-macro worktree imports. Those mechanisms need their own maintenance justification.

## Commands and controls

The screen uses the same optimized compiler, Cargo and runtime bytes in both arms on `charlie-oss-2` (boot `f0ea9684-5bb5-4daa-8429-1f38885bc4bb`). Full keeps the shipping defaults; reduced adds only `-Zcache-proc-macros=no` through the benchmark’s pinned compiler policy. Public API hashing and every non-axis default stay equal. Each arm starts with empty private target and shared histories, then runs cold, warm no-op and the three original edits with eight jobs. These are selected library checks, with zero project test executions:

- Ruff: `cargo +<arm> check --locked --offline --lib -p ty_python_semantic -p ty_python_core`
- uv: `cargo +<arm> check --locked --offline --lib -p uv-pypi-types -p uv-client`
- Codex, in `codex-rs`: `cargo +<arm> check --locked --offline --lib -p codex-tui`

The exact original patches, fixture source inventories and lockfiles are retained. Ruff edits alter attribute inference, uv edits alter Simple API parsing and compatibility tests, and Codex edits alter active-cell rendering and invalidation. uv’s third edit may be inactive for these library targets. Earlier untimed uv admission observed 98 and 62 persisted derive-result loads after two edits; that demonstrates activation without attributing every timed command to cache hits. Source-only workload preparation from the resolver screen is reused explicitly; no prepared outputs seed timed histories.

## Every command state

Positive deltas mean disabling the cache was slower. Medians are computed from paired differences; they need not equal the difference of arm medians. The ranges are the two observed differences, with one pair in each arm order. They are not confidence intervals.

| Project | State | Default median | Disabled median | Paired median delta | Paired range | Disabled slower |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ruff | Cold | 33.679 s | 32.257 s | -1.422 s | -6.855 to +4.011 s | 1 / 2 |
| ruff | Warm no-op | 0.514 s | 0.466 s | -0.048 s | -0.212 to +0.115 s | 1 / 2 |
| ruff | Edit 1 | 8.676 s | 8.696 s | +0.020 s | -0.708 to +0.748 s | 1 / 2 |
| ruff | Edit 2 | 10.537 s | 12.623 s | +2.087 s | +2.017 to +2.157 s | 2 / 2 |
| ruff | Edit 3 | 11.680 s | 12.385 s | +0.705 s | +0.428 to +0.982 s | 2 / 2 |
| uv | Cold | 50.565 s | 50.423 s | -0.142 s | -0.502 to +0.217 s | 1 / 2 |
| uv | Warm no-op | 0.897 s | 0.807 s | -0.090 s | -0.240 to +0.059 s | 1 / 2 |
| uv | Edit 1 | 5.056 s | 5.105 s | +0.048 s | +0.010 to +0.087 s | 2 / 2 |
| uv | Edit 2 | 1.436 s | 1.360 s | -0.076 s | -0.189 to +0.036 s | 1 / 2 |
| uv | Edit 3 | 4.412 s | 4.448 s | +0.036 s | -0.140 to +0.213 s | 1 / 2 |
| codex | Cold | 152.994 s | 150.406 s | -2.588 s | -4.212 to -0.964 s | 0 / 2 |
| codex | Warm no-op | 2.077 s | 2.132 s | +0.056 s | -0.326 to +0.437 s | 1 / 2 |
| codex | Edit 1 | 9.602 s | 8.969 s | -0.634 s | -0.902 to -0.365 s | 0 / 2 |
| codex | Edit 2 | 7.407 s | 6.343 s | -1.064 s | -1.119 to -1.010 s | 0 / 2 |
| codex | Edit 3 | 7.193 s | 6.793 s | -0.401 s | -0.544 to -0.257 s | 0 / 2 |

Codex’s cold saving is a paired median 2.59 seconds, with a range of 0.96–4.21 seconds. Its edited checks save 0.63, 1.06 and 0.40 seconds. Ruff’s cold, no-op and first-edit differences change sign between pairs; its second edit loses about 19.8% in both. Report these states separately rather than hiding their opposing effects in a history total.

## Acceptance and evidence

All six pairs, 60 command logs and 15 command statistics passed independent root audit. It rechecked 1,164 continuous monitor samples and 96 required quiet samples, all source/lock/status parity, actual successful supervisor exits and positive child/group/lease release. The immutable archive has 648 safe unique regular members; all 647 payload hashes, sizes and original modes, all 24 readiness proof bodies and all six final controller receipts were independently verified. The existing source, native, optimization and runtime evidence is reused. Earlier rejected whole campaigns remain excluded; their partial cells were not imported into this fixed screen.

Maximum child RSS is available per command in the raw statistics and is not aggregate memory. Successful statuses and raw log hashes do not establish exact warning-text equivalence. No statistical significance or combined-stack speedup is claimed. No follow-up timing campaign has been started.

- [All command statistics and raw cell values](proc-default-oss2-screen-01/proc-complete-command-root-review-01.json)
- [Final root acceptance](proc-default-oss2-screen-01/proc-complete-root-review-01.json)
- [Complete immutable raw archive](proc-default-oss2-screen-01/capture-complete-02/raw.tar.gz.not-included.md)
- [Raw packet manifest](proc-default-oss2-screen-01/capture-complete-02/packet/validation/proc-default-complete-02/packet.json)

