# Compiler driver self-binding on uv #21577

The edited uv_warnings compiler retired **21.384% and 21.381% fewer instructions** on two independent AMD EPYC workers running glibc 2.39. All 16 pairs cleared the preregistered 20% threshold. The whole Cargo invocation retired 5.42% fewer instructions on both workers. Its separately measured median paired wall time fell 2.98% and 3.76%, with slower individual pairs on both workers. [Landed uv edit](https://github.com/astral-sh/uv/pull/21577).

The study compares the authenticated Ohm 1.99.0 −23 compiler with a private image of that compiler. The image locally binds 8,733 references to internal strong functions and places their relative relocations in the linker’s fast prefix. Both sides used the signed Cargo and the original landed twelve-file edit.

Each worker ran eight balanced pairs of first edits in 16 independently built A histories. Each visit checked both original rustc invocations and their inputs, unchanged A and B no-ops, and all 39 raw metadata and 30 public sidecar products against an independent cold B. Linked consumers confirmed the real change in warning hint order. The primary requires at least 20% fewer retired user instructions in uv_warnings in every pair and each half median on both independent calibrated workers.

| Worker | uv_warnings | uv_errors | Both rustcs | Whole Cargo instructions | Bare Cargo wall | Primary passes |
|---|---:|---:|---:|---:|---:|---:|
| [41612056250](https://github.com/astral-experiments/ohm/actions/runs/41612056250) | +21.384% | +5.608% | +8.886% | +5.421% | +2.975% | 8/8 |
| [41612235937](https://github.com/astral-experiments/ohm/actions/runs/41612235937) | +21.381% | +5.608% | +8.886% | +5.422% | +3.756% | 8/8 |

The table shows median paired percentage reductions. report.json contains all raw counts, wall intervals and both half decisions. The earlier original-position relocation experiment remains separately recorded. The local grouped experiment and the original-position experiment are separately retained under mechanism/. The four native address audits include a deliberate preload override. Both binaries retain all 7,516 exports. Local references to the selected function bind inside the prototype’s driver with the override present. This diagnostic measures that specific Linux/ELF transformation and edit.

Run **python3 -ISB verify.py** to reopen both complete original Actions archives, hash the recorded products, match the raw hardware counter words to kernel process events, and recalculate both hosts’ decisions. [Frozen worker](https://github.com/astral-experiments/ohm/tree/c126e7b93092473f751185aa83d7f6c9712037aa/scripts/driver-bind-21577).
