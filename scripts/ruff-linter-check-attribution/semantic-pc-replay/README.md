# Where the signed Rust compiler spent instructions on Ruff #27470

One real dirty `ty_python_semantic` rustc process retired **14,498,548,985 user instructions**. Its sampled instruction pointers divide among the signed compiler driver (77.97%), the Salsa proc-macro library (13.90%), other macro libraries (1.50%), libc (2.94%), the rustc executable (2.82%), the ELF loader (0.26%) and the remaining 0.60%. The last group includes 84 kernel-skid samples. The largest single symbol was incremental dependency validation at 7.70%. This one-process profile provides a work budget. It does not measure a candidate speedup.

The command was `cargo +ohm check -p ty_server --lib --locked --offline --message-format=json` on the genuine historical Ruff edit c6c4d38bbeeae91fe59d9c277a78169db8306561 → 97065696c0e4dbe6ff43a89c73f923bf60ee231a. The official Linux -23 archive was 359,921,838 bytes, SHA-256 `fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b`. Native Rust was d57fd1515986dccecdcece8da85e651bfb4b81f9 and Cargo was 7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed. This acquisition used one fresh worker after the distinct signed ownership census. [Profile registration](https://github.com/astral-experiments/ohm/blob/b25442589d86ea709d9be177c54b815c878be945/scripts/ruff-linter-check-attribution/SEMANTIC-PCS.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41573331247) · [Prior whole-Cargo and 12-owner counters](https://github.com/astral-experiments/ohm/blob/8095401c9f349463b1b6ab370bfc4fbc1a479672/scripts/ruff-linter-check-attribution/signed23-replay/README.md)

## Physical evidence

Linux perf recorded 25,243 original hardware `instructions:u` samples over Cargo and its descendants. The 14,488 samples after the genuine compiler exec in PID 7002 and its 11 threads represent 14,488,043,464 instructions at period 1,000,003. That is 99.93% of the independent, disjoint counters on that same native image. The kernel recorded zero dropped or throttled samples. Both chronology and every original IP, PID, TID, timestamp, weight and delivered instruction event agree with a second binary decoder. The original full profile SHA-256 is `795746bd55cb4fd94a43a06d74420b26bfda5298664f0d64d60b3417e5755495` (1,814,132 bytes).

The kernel stopped the 12 real edited rustcs and captured their original NUL-delimited argv and executable inode. All 12 match the earlier signed run after its single permitted Cargo output shard substitution. Edited and repaired argv on this worker are literally identical. The physical compiler counts across cold old, unchanged old, edit, unchanged new, invalid, repair and independent clean new were **283 / 0 / 12 / 0 / 1 / 12 / 283**. The invalid source produced the registered E0308 at its actual span. All 31 workspace metadata files agree warm, unchanged and repaired; 7/31 warm files are byte-equal to independent clean. The per-definition decoder reproduced the earlier signed differences on four actual metadata archives under each old, edited and independent clean build. Cargo's 279 typed units, historical graph and error/repair verdicts agree. This was a library check, with metadata as its output.

## Exclusive signed-driver samples

The table assigns each *bounded leaf function name* to a single row. Percentages use **all 14,488** compiler samples as the denominator. Monomorphized names containing several namespaces follow the documented classifier order. These rows describe executing symbols, an imperfect proxy for stages in a compiler with extensive inlining.

| Signed driver symbol family | Samples | Compiler share |
| --- | ---: | ---: |
| Dependency graph, including generics specialized for its index | 2,290 | 15.81% |
| Parsing and lexing | 1,296 | 8.95% |
| Name resolution | 1,136 | 7.84% |
| Other named stable hashing | 1,026 | 7.08% |
| Macro expansion and proc-macro bridge | 833 | 5.75% |
| Public API hashing and reachability | 791 | 5.46% |
| AST lowering | 776 | 5.36% |
| Other named query infrastructure | 735 | 5.07% |
| Other metadata | 450 | 3.11% |
| Other driver symbols | 1,889 | 13.04% |
| Ambiguous or unresolved driver symbol | 75 | 0.52% |

The first four unaliased leaves were `DepGraphData::try_mark_previous_green` (1,116), `LateResolutionVisitor::resolve_path` (245), `Lexer::next_token_from_cursor` (245), and `LoweringContext::lower_qpath` (214). Other concrete leaves included `MacroExpander::fully_expand_fragment` (204), `SerializedDepGraph::try_decode` (199), the public API instantiation of `EncodeContext::encode_def_ids` (197), `Resolver::resolve_ident_in_scope_set_inner` (190), a proc-macro server dispatch closure (170), and `ReachabilityGraphBuilder::build_graph` (151). The replay contains the complete leaf table.

The signed driver was independently streamed from the physical release archive. Its full 162,671,488 bytes match SHA-256 `53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52` and live build ID 13d77347e7b9583b23105b596b85d283cd70af08. The binary contains both symbol tables. It was BOLT-linked with identical-code folding and carries no DWARF line or inline tables. Across body-qualified DSOs, 11,721 samples lie in bounded ELF symbols and 448 have unresolved symbols. Another 2,235 user-space samples fail the original strength of full mapped-file identity, detailed below. The full-range tier yields zero source-line or inlined-frame attributions. Perf's frame-pointer callchains lack a caller for most samples (9,515 chains of length one); every reported workload share here charges a leaf once.

The 4,046-byte original `try_mark_previous_green` function is fully disassembled and independently checked. All 106 distinct observed PCs sit at real x86 instruction boundaries. A dense cluster of 570 sampled PCs falls at 0x5cec841, after the lock-compare-exchange used when promoting and coloring a node, and 122 at 0x5cec6f5, after an indexed color-map load. This event has ordinary interrupt skid. Treat the cluster as a location within promotion and color checking; its 570 samples do not establish that a packed integer-add instruction is itself expensive. The source preserves concurrent green/red publication and checks every dependency. Earlier work addresses edge-array reuse and index bounds on this path. [Signed graph traversal](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_middle/src/dep_graph/graph.rs#L1054-L1137) · [Signed promotion and coloring](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_middle/src/dep_graph/serialized.rs#L1035-L1064) · [Edge reuse PR](https://github.com/astral-experiments/ohm-rust/pull/11) · [Index-bound PR](https://github.com/astral-experiments/ohm-rust/pull/265)

## The Salsa mapping

The 2,014 Salsa leaf PCs each fall unambiguously inside the original executable MMAP2 in the same rustc PID. Cargo identifies that exact filename as the already built registry package `salsa-macros@0.28.2`. Perf reported 449 distinct symbol names in this shared object. The independent reader checks the original perf build-ID feature against its kernel image name and the original sampled symbol rows. The 20-byte recorded ID is `6aa564f2863239fab2868eaf13622458794d8c9b`. It matches the prefix of the independently empty build's full 32-byte ELF build ID `6aa564f2863239fab2868eaf13622458794d8c9b56c63595324714035f679ea3`. That replacement weighs 5,644,160 bytes and has full SHA-256 `95ea8231d1af6b737c629d97761bb23a33e582478779f856f4e1af1e4d4f63b3`. The original and clean inodes differ. The raw archive retains the original prefix and symbol names; it lacks the original full Salsa file. For another macro, GetSize, the prefix itself changed across clean. The replay retains that mismatch.

Grouping the Salsa names by their first named Rust crate yields 658 core, 474 syn, 280 alloc, 263 proc_macro, 236 proc_macro2, 39 __rustc, 14 hashbrown, 7 salsa_macros, 6 std, 1 quote and 36 other or unidentified samples. The heavy individual names include `Ident::spec_to_string` (79), `syn::buffer::Cursor::peek_punct` (59), string equality (50), a byte-slice iterator (47), character enumeration (46), `RawVecInner::finish_grow` (42), and `syn::parse::ParseBuffer::cursor` (35). Among these independent symbol groups, monomorphized core code can execute for syn/proc-macro inputs. None of the name counts claim a distinct invocation count or source-line attribution.

Based on this localization, a diagnostic that distinguishes repeated pure macro expansion from token bridge/parsing work has a larger budget than a single green-marking micro-optimization. All original kernel-mapped proc-macro DSOs account for 2,232 samples. Even removing every one of those samples **and** every one of the 833 signed expansion/bridge samples would reach only 21.16% of this compiler and about 12.13% of the separately measured whole check. The dependency-graph family corresponds to about 9.07% of that check. Both are generous algebraic ceilings, before replacement work and correctness for tracked inputs, spans, hygiene and observable macro behavior. These data alone do not support a twofold whole-check change.

## Reproduce

The literal GitHub Actions archive is retained here (artifact 13202148570, 6,449,572 bytes, SHA-256 `df3081a35e1daffbafe4ce38956515ea52ff7355d72c837cf5265ff722ab46dd`). From this checkout on Linux with Python 3.12, zstd and LLVM 18's llvm-cxxfilt installed:

```sh
python3 -IB scripts/ruff-linter-check-attribution/semantic-pc-replay/replay.py --mutations
```

Optionally add `--driver /absolute/path/to/librustc_driver-b03bf00bec23bb9a.so` from that signed release. This version also checks every sampled signed-driver symbol interval and every observed instruction in its hottest function against local ELF bytes with nm, readelf and objdump. The five mutation controls alter an actual sampled IP, a kernel-stopped compiler argv, a bounded ELF symbol range with a newly computed inner transport hash, a macro build-ID prefix, and the real error diagnostic. Each is rejected.

The complete archive and original raw record stay separate from `native-and-pcs.json`, `disjoint-and-salsa.json` and `signed-native-hot.json`. The latter two contain supplemental physical-mapping/source-code analysis. The earlier signed ownership and experimental compilers contribute zero samples here.
