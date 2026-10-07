# Coroutine layout/debug projection ablation

**Recommendation: remove the coherent #99/#132 bundle.** The measured benefits of retaining its separate layout and debug projections are small and mixed. Removal improved both cold Ruff builds by a two-pair median 1.777 seconds, both Ruff builds after Edit 2 by 0.816 seconds, and both Ruff builds after Edit 3 by 0.543 seconds. Both uv cold builds and builds after Edits 1 and 2 favored removal by 0.655, 0.211 and 0.121 seconds.

Retaining the bundle helped both Codex no-ops and builds after Edit 1: removal added medians of 0.144 and 0.433 seconds. Codex builds after Edits 2 and 3 favored removal by 0.331 and 1.506 seconds in both orders; its cold-build result was mixed. These small gains from retention do not justify the extra compiler layout, metadata and debug query paths for this simplification goal.

The treatment removes the two families together across eighteen declared source paths. It returns consumers to the ordinary coroutine layout query and preserves async-drop handling, error-tainted/custom MIR handling and the accepted full-debug option. The experiment does not attribute a separate benefit to either PR. [Rust #99](https://github.com/astral-sh/ohm-rust/pull/99) and [Rust #132](https://github.com/astral-sh/ohm-rust/pull/132) are the coherent measured bundle. #138 is absent from the frozen shipped pin and contributes no code to this comparison.

The commands build selected real libraries with `--locked --offline --lib` and eight jobs: Ruff's `ty_python_semantic` and `ty_python_core`, uv's `uv-pypi-types` and `uv-client`, and Codex's `codex-tui`. Each arm starts with empty private target/shared histories. Each project has two complete pairs, one in each order. The five phases are cold build, warm no-op, and builds after original Edits 1, 2 and 3. All three frozen original edits are applied; uv's third edit may not affect its selected libraries. No broad test suite is timed.

Edits 1, 2 and 3 follow each project’s recorded source history in order. Ruff simplifies recursive attribute inference, indexes implicit attribute dependencies, then adds component fixed points. uv implements the dedicated Simple API JSON parser, simplifies its implementation, then simplifies compatibility tests. Codex adds transcript layout bookkeeping, implements stable active-cell rendering and snapshots, then invalidates cached layouts when active cells are removed. Each state retains the previous edits; the third uv edit may be inactive for the selected library commands.

## Command time

Seconds are command wall time, excluding preparation, source-proof collection, quiet waits and cleanup. Brackets give the observed two-sample range. Each percentage compares removal against full within its fixed pair; positive means removal was slower. Ranges are not confidence intervals.

| Project | State | Full median [range], s | Removed median [range], s | Median change, s | Pair 0 | Pair 1 |
|---|---|---:|---:|---:|---:|---:|
| ruff | Cold build | 51.716 [50.236, 53.197] | 49.939 [49.770, 50.108] | -1.777 | -5.81% | -0.93% |
| ruff | Warm no-op | 0.402 [0.397, 0.407] | 0.442 [0.371, 0.513] | +0.040 | +29.24% | -8.93% |
| ruff | Edit 1 | 18.510 [17.485, 19.536] | 17.823 [17.764, 17.881] | -0.688 | -8.47% | +1.60% |
| ruff | Edit 2 | 25.375 [24.723, 26.027] | 24.559 [24.487, 24.631] | -0.816 | -5.36% | -0.96% |
| ruff | Edit 3 | 28.842 [28.750, 28.933] | 28.299 [28.209, 28.389] | -0.543 | -2.50% | -1.25% |
| uv | Cold build | 45.601 [45.350, 45.853] | 44.946 [44.826, 45.066] | -0.655 | -2.24% | -0.63% |
| uv | Warm no-op | 0.652 [0.637, 0.667] | 0.581 [0.560, 0.603] | -0.070 | -12.13% | -9.52% |
| uv | Edit 1 | 5.453 [5.425, 5.481] | 5.242 [5.221, 5.262] | -0.211 | -3.00% | -4.74% |
| uv | Edit 2 | 3.884 [3.878, 3.891] | 3.764 [3.744, 3.784] | -0.121 | -2.43% | -3.77% |
| uv | Edit 3 | 3.823 [3.803, 3.843] | 3.820 [3.785, 3.856] | -0.002 | +0.35% | -0.48% |
| codex | Cold build | 194.339 [193.564, 195.114] | 194.232 [194.172, 194.292] | -0.107 | -0.48% | +0.38% |
| codex | Warm no-op | 2.191 [2.120, 2.262] | 2.335 [2.312, 2.359] | +0.144 | +11.23% | +2.21% |
| codex | Edit 1 | 15.918 [15.654, 16.182] | 16.351 [16.319, 16.383] | +0.433 | +0.84% | +4.66% |
| codex | Edit 2 | 13.833 [13.506, 14.160] | 13.502 [13.271, 13.732] | -0.331 | -3.02% | -1.74% |
| codex | Edit 3 | 13.100 [12.872, 13.327] | 11.594 [10.672, 12.516] | -1.506 | -2.76% | -19.92% |

## Maximum child RSS

MiB from GNU time for each command: maximum child-process RSS, not the sum of simultaneous compiler processes. The changes are small or mixed and do not establish an aggregate memory saving.

| Project | State | Full median [range], MiB | Removed median [range], MiB |
|---|---|---:|---:|
| ruff | Cold build | 3366.893 [3293.227, 3440.559] | 3284.186 [3282.578, 3285.793] |
| ruff | Warm no-op | 62.578 [62.520, 62.637] | 61.807 [61.602, 62.012] |
| ruff | Edit 1 | 3567.854 [3557.957, 3577.750] | 3478.426 [3475.309, 3481.543] |
| ruff | Edit 2 | 4387.148 [4345.047, 4429.250] | 4379.273 [4377.082, 4381.465] |
| ruff | Edit 3 | 4471.967 [4465.984, 4477.949] | 4394.301 [4390.105, 4398.496] |
| uv | Cold build | 971.863 [969.062, 974.664] | 977.994 [966.992, 988.996] |
| uv | Warm no-op | 92.131 [92.102, 92.160] | 91.996 [91.863, 92.129] |
| uv | Edit 1 | 981.877 [978.992, 984.762] | 983.787 [969.332, 998.242] |
| uv | Edit 2 | 894.475 [883.688, 905.262] | 906.682 [899.051, 914.312] |
| uv | Edit 3 | 904.387 [901.387, 907.387] | 895.814 [891.102, 900.527] |
| codex | Cold build | 3381.682 [3372.434, 3390.930] | 3382.912 [3379.121, 3386.703] |
| codex | Warm no-op | 184.242 [184.059, 184.426] | 184.238 [184.211, 184.266] |
| codex | Edit 1 | 3828.592 [3825.488, 3831.695] | 3847.064 [3842.250, 3851.879] |
| codex | Edit 2 | 3068.670 [3062.535, 3074.805] | 3014.199 [3004.617, 3023.781] |
| codex | Edit 3 | 2684.885 [2680.285, 2689.484] | 2620.025 [2614.758, 2625.293] |

## Retained-history storage

GiB measured at the end of each arm, after its fifth command. The allocated column sums each target/shared-build/format-cache root's `lstat` blocks. The unique column deduplicates inodes across those roots. These are retained-history endpoints, not peak or per-command storage, and do not measure total compiler installation size. The exact raw root values and result hashes are retained in the detailed JSON.

| Project | Arm | Allocated median [range], GiB | Unique inode allocated median [range], GiB |
|---|---|---:|---:|
| ruff | Full | 1.821 [1.821, 1.821] | 1.575 [1.575, 1.575] |
| ruff | Removed | 1.823 [1.823, 1.823] | 1.576 [1.576, 1.576] |
| uv | Full | 1.515 [1.515, 1.515] | 1.469 [1.469, 1.469] |
| uv | Removed | 1.515 [1.515, 1.515] | 1.470 [1.470, 1.470] |
| codex | Full | 9.745 [9.745, 9.745] | 9.302 [9.302, 9.302] |
| codex | Removed | 9.744 [9.744, 9.745] | 9.301 [9.301, 9.302] |

## Correctness, source and optimizer provenance

The source comparison is bound to the exact shipped pin `348339ddae4288ebb3af97d204b19479fef8f5f2`, the accepted coherent removal patch and its eighteen-path inventory. The other component sources, resolved release config, common Cargo and original release/training plan are retained. All eleven training commands were checked: seven nonformatter commands preserve order; four formatter batches match as a full-command multiset. Each compiler arm has its own source-dependent PGO/BOLT outputs. This compares the optimized release bundles after source removal, not identical-profile binaries or the runtime cost of one query in isolation.

The accepted native evidence covers 25 new reduced compiletests and three source units, with the accepted baseline 25+3 reused. It also covers four private-layout callbacks, twelve debugger cases with 32 original full-debug variable checks, 44 linked histories and fifteen header checks. This is bounded correctness evidence, not a claim that the entire compiler or debugger suite passed. Line-table tests establish stops/backtraces; unsupported variable/type commands remain recorded, and the CDB-only case is excluded on Linux. Unique ELF provider definitions were checked without a new `LD_DEBUG` binding trace. Smoke diagnostic parity is an accepted generated-receipt assertion, not an independent reconstruction of absent separate diagnostic streams. The successful benchmark statuses and raw log hashes likewise do not claim exact warning-text equivalence.

Each timing arm binds the accepted 69,859-file installed runtime map, original modes, current metadata and its own loader graphs. The full baseline byte evidence is reused with current size/mode/device/inode/link checks; the current reduced payloads were hashed and disjoint runtime inodes verified. These are explicit pinned-host verifier assertions; installed runtime binaries were not included in the final raw archives. All shipping/metadata normalization preserves the generated originals and requires the exact accepted original text-file hashes. No compiler, library or optimizer-profile bytes were substituted to normalize installer metadata.

## Timing and evidence limits

Ruff and uv each ran both orders on `charlie-oss-0`, a 32-CPU host, boot `68db8bb3-5bac-4c42-8902-017b488cf59a`. Codex's two prospectively assigned orders ran on `charlie-serc-direct-2`, also 32 CPUs, boot `f4dcfa8c-16f9-466f-a366-dfe3a66d3d09`. Within-project deltas retain one host; absolute samples are not pooled across hosts. Codex was never measured on the original oss0 host. The original six-slot schedule and separate Codex two-slot schedule remain distinct.

All six measured attempts were accepted whole pairs. Preparation, transport, installer-metadata and the first raw collector path failure remain preserved separately and supply no timing cells. The final archive correction maps the two exact task roots to the existing flat task layout and `rust-root/`; raw hashes, original modes, release checks and measurement gates remain unchanged. Both archive readers and collectors returned zero after the corrected collection. The final Direct2 read-only closure reports all four recorded timing PID/start/group identities gone, no bounded users, no leases and no compiler processes. The oss0 block has its accepted bounded closure; no fresh global compiler-free claim is inferred there.

The original noise thresholds, complete six-sample quiet windows, continuous monitor, source/lock checks, command/parity statuses and positive release receipts remained enforced. The combined command audits cover six pairs, 60 timed commands, fifteen states, 1,557 continuous monitor samples and 144 required quiet samples. The final independent root review accepts all six pairs and independently recomputes every timing, RSS and endpoint-storage cell. Its Direct2 catalog review rehashes 41 proof bindings across 40 distinct bodies; the source-checks body supplies two proof kinds with the same pinned hash.

Raw blocks: [Ruff/uv evidence](oss0-retained-four-raw-retrieved-dbox-01/packet/README.md) and [Codex evidence](direct2-complete-raw-retrieved-dbox-01/human-packet/README.md). All accepted result hashes, paired observations, RSS and endpoint-storage values are in [the detailed data](coroutine-detailed-results.json). The original native limitations are in [the native review](oss0-retained-four-raw-retrieved-dbox-01/packet/readiness/coroutine-oss0-public-inputs-01/native-root-review.json).

Final acceptance: [the combined root review](coroutine-final-root-review-01.json) (`ec73d530ee95bb4c0fec4dc006c85b58b1aae9910adabaf16bdd83e17ee4c84b`).
