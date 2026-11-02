# Reconstructing native debug locations from ordinary compiler inputs

Ruff #28106's 21 reoptimized `ruff_workspace` modules supplied independent Old and New `DIFile` records, typed checksums and distinct line arrays. Sorting each file's positive lines defines a compiler-local ordinal. The predictor admitted 19 equal pre-backend module keys and rejected both actual native changes before opening either New object. It used each Old ELF and its previous/current IR tables to regenerate the two debug sections. All 19 complete predicted ELF objects matched both the actual incremental New build and an independently empty New build. The predictor blocked source-file reads and subprocesses. [Original compiler input evidence](https://github.com/astral-experiments/ohm/tree/fda8bcd899ec1843839c350c118d556af75710fe/scripts/ruff-option-cgu-identity)

The earlier 19 matches describe this particular edit. LLVM also compares physical line numbers across files when it sets DWARF `is_stmt`. Actual signed LLVM objects in `signed-is-stmt.tar.gz` show an instruction at `.text+6` gaining `is_stmt` when `b.rs:70` becomes `b.rs:71` after `a.rs:70`. The 71→72 case leaves the flag unchanged. Certifying a single strictly increasing mapping for all previous physical lines in a module, including 0→0 and 1→1, accepts 15/21 here. These 15 account for 83,908,903,279 of 120,906,271,208 instructions in the fixed LLVM IR optimization/emission replay. A complete Cargo command and the cost of constructing or consuming these records have not been measured. [LLVM statement emission](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/CodeGen/AsmPrinter/DwarfDebug.cpp#L2286-L2312)

## Prior storage

| Previous records | Bytes for all 21 | Percent of 14,348,624 Old object bytes |
| --- | ---: | ---: |
| Flat u32 source lines | 147,023 | 1.025% |
| Delta-ULEB source lines | 113,071 | 0.788% |

The delta records range from 926 to 14,532 bytes per CGU. Both independently generated roles have the same aggregate size. Each prior record includes the semantic key, every full logical pathname, its typed checksum and the complete per-file line arrays. Files are sorted. The two encodings differ only in the representation of the positive lines. The 15 conservative prior records cost 62,550 bytes for 8,499,472 native object bytes. A subsequent build needs one prior generation and its new in-memory compiler input; the calculation charges a full path and checksum in every module with no cross-module deduplication.

The existing Old ELF alone does not encode the original IR ordinals. All 4,415 observed positive `(file, line)` pairs had an IR entry. Sorting only the object's visible rows and DIE references gave 3,785 different ranks, three of them in the edited source. For example, one actual Old call site is `options.rs:1718`. Its rank in that object's visible lines was 1 and its rank in the earlier IR was 2. Using rank 1 would have produced line 1720. Both actual New objects say 1722. An object that initially emitted ordinals could avoid retaining the Old physical-to-ordinal map, but the debugger-facing output would still need the current map and physical line-dependent flag decisions. This artifact does not contain an ordinal-coordinate object or a measured storage cost for presenting it.

## Reproduce

`python3 -IB verify.py` recomputes all 42 wire records and projects the retained controls from the parent packet. `python3 -IB verify.py --original /path/to/ordinary-13109144871.zip` verifies all 21 original inputs and the complete warm and independently clean New native outputs. The compact records include source/IR/native digests, each unit's wire size, and the two independent decision flags. The signed cross-file control includes the raw LLVM module, its emitter, three actual objects and decoded debugger rows. [Original native archive and rerun](../README.md)

The signed two-file control also steps the actual executables in GDB. An unchecked 70→71 rewrite skips `b.rs:71` and lands at `a.rs:91`; fresh LLVM stops at `b.rs:71`. [Full stepping control and 15-unit audit](https://github.com/astral-experiments/ohm/blob/28f2ad253a6252632ba3a8a64dfe109a61fd99e4/scripts/ruff-cross-file-line-order/README.md)
