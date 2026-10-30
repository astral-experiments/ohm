# Ruff AST developer builds with Rust #276 and Cargo #293 on Apple silicon

On two mirrored pairs, Rust #276 removed one full `zmij` compilation from each edited and unchanged Cargo command. The library's exact native-output check failed. The test build passed its output checks, but both compilers still dispatched a link-only rustc on each unchanged invocation. This run collected **zero timing or instruction samples**. [Original native run](https://github.com/astral-experiments/ohm/actions/runs/41082498619) · [Frozen protocol](https://github.com/astral-experiments/ohm/blob/1144be19f9442ad500dc30a5b3102e7efb4aa12c/scripts/ohm-apple-zmij/ast293-debug-names-plan.md)

The parent was Rust #275 `2035696c5316079f5b2e4373aee834839aac97e9`, and the candidate was #276 `444c0273a2e2bc0b161e988d43c882349bc2d7a6`. Both used one physical Cargo #293 `735e1528ed741015c57676dccf05dbdc0ff7bed1`. Each native installation excluded `CI` and `TF_BUILD`. Actual local Ruff compiler arguments contained `-Cincremental`, and the corresponding on-disk Ruff session contained native objects, a dependency graph and work products. The 392 native provider commands met all required behavioral and output checks. [Native provider registration](https://github.com/astral-experiments/ohm/blob/1144be19f9442ad500dc30a5b3102e7efb4aa12c/scripts/ohm-apple-zmij/fixed_crc.py)

## Actual Cargo-launched work

Each cell counts **full rustc / link-only rustc / Xcode ld**. Every count reproduced in both acquisition orders. Library used parent then candidate and candidate then parent. Test used candidate then parent and parent then candidate.

| Ruff command | Source state | Parent | Candidate |
|---|---|---:|---:|
| Build AST library | Cold | 39 / 0 / 8 | 39 / 0 / 8 |
| | Real edit, invalid, repair, each | 2 / 0 / 0 | 1 / 0 / 0 |
| | First and second unchanged, each | 1 / 0 / 0 | 0 / 0 / 0 |
| Build AST unit tests | Cold | 36 / 0 / 9 | 36 / 0 / 9 |
| | Real edit and repair, each | 2 / 0 / 1 | 1 / 0 / 1 |
| | First and second unchanged, each | 1 / 1 / 0 | 0 / 1 / 0 |
| | Invalid edit | 2 / 0 / 0 | 1 / 0 / 0 |

On both unchanged test builds, the link-only process was `ruff_python_ast`. Both returned without invoking Xcode ld. The source edit and repair each produced a newly linked executable. The 53-test old suite and 54-test new suite passed their complete expected outcomes. The invalid edit produced E0425. All 20 valid warm-versus-empty test comparisons passed their registered signed-image and physical native-input checks. All four independent empty-versus-empty test pairs also passed. The first study required zero link-only rustc invocations in both arms to admit timings.

## Exact library comparison

Ten of the 20 warm-versus-empty library comparisons differed. All six distinct unlike pairs had the same 13,167,888-byte length, archive headers, member names, symbol index, all 95 codegen objects and `lib.rmeta-link`. The linked external client's whole executable, machine instructions and typed result matched each time. Only the 5,901,952-byte `lib.rmeta` member differed, by either 62 bytes in 11 ranges or 90 bytes in 16 ranges. All changes fall inside the Apple ARM64 metadata object's `__DWARF,.rmeta` section. The protocol required exact Rust metadata and rejected those pairs.

| Independent empty build 1 vs empty build 2 | Old Ruff source | New Ruff source |
|---|---|---|
| Parent compiler | 62 differing `lib.rmeta` bytes, 11 ranges | Complete library identical |
| Candidate compiler | 62 differing `lib.rmeta` bytes, 11 ranges | Complete library identical |

The old-source metadata variation reproduced on a fixed compiler with two independently empty target and shared directories in each role. The native client exercises the historical API change. The meaning of the differing metadata bytes remains unresolved. [All original member and range comparisons](observations.json)

## Reopen the evidence

Run `python3 -IB verify.py` in this directory with `zstd` on PATH. It reconstructs complete returned files, checks both independent empty references per source and role, reopens the native inputs and every signed page of the observed test executables, and recomputes the table from the original kernel events and typed Cargo responses. It uses about 250 MiB of RAM and writes no build products. [Portable verifier](verify.py)

The original GitHub Actions final artifact was 90,636,508 bytes, SHA-256 `b8ae4985fd2a05c381505e616f4ce3b76d98556672b30f55ce3eb3e450756a87`. The compact packet is 5,557,775 bytes and contains lossless content from 984 selected original members, including all ten complete libraries, all native Ruff test executables and client readers, actual Cargo/kernel streams, required recipe/object bodies and both independent clean controls. The manifest records the digest of every selected original ZIP member and its decoded body. [Artifact custody](custody.json) · [Native output packet](native-outputs.tar.zst) · [Original Actions artifact](https://github.com/astral-experiments/ohm/actions/runs/41082498619/artifacts/12989739951)
