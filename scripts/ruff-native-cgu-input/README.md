# Native LLVM input identity for Ruff’s option-documentation edit

An independent LLVM 23 reader found the same native-code candidate in 15 of the 21 dirty `ruff_workspace` codegen units. It worked from each current LLVM module and the arguments of its ordinary signed Ohm -22 compilation. Four more units whose allocated object bytes matched fell outside the conservative cross-file line-order rule. The two units with observable code or data changes produced different keys. [Original Cargo capture](https://github.com/astral-experiments/ohm/actions/runs/41371190920) · [Per-unit source and native ELF analysis](https://github.com/astral-experiments/ohm/tree/fda8bcd899ec1843839c350c118d556af75710fe/scripts/ruff-option-cgu-identity)

The ordinary crate used opt-level 1, incremental compilation, line tables only, LTO off and no embedded bitcode. The reader verifies this mode, clones the current module, runs stock `deadargelim,globaldce`, and rewrites typed debugger coordinates to a single ordering across all source files. It preserves 0 and 1, file identity, checksum kind, column, scope, discriminator, inlining structure, attributes and the rest of the serialized module. Each current placement table carries the actual recorded checksum and source coordinates. All 42 original modules remained intact. Applying each set of current coordinates to the normalized module recovered the complete post-pass LLVM bitcode byte for byte.

| Current input work across all 21 dirty units | Callgrind guest instructions |
| --- | ---: |
| Check eligibility | 676,019,833 |
| Clone the native module | 1,871,313,224 |
| Stock dead-argument and global elimination | 141,788,470 |
| Typed rewrite, verification, serialized bitcode SHA-256 and current placement encoding/hash | 4,897,081,735 |
| Destroy private module | 256,255,787 |
| Remaining policy operations | 3,192 |
| **In-memory policy** | **7,842,462,241** |
| Parse and verify the serialized capture, separately | 3,908,761,345 |
| Entire standalone path, including destruction of the ordinary module and LLVM context | 12,261,923,442 |

All 105 named stage counts in the separate 21 complete captures reproduced their counts in the initial 45-region collection. The repeated positive independently reproduced 323,132,500 parse and 620,040,715 policy instructions. The baseline fixed backend replay consumed 120,906,271,208 instructions; the 15 matching units account for 83,908,903,279. The remainder before reaching half the original work is 15,613,305,434 after charging the entire in-memory reader. This arithmetic excludes object reconstruction and all work outside the backend. Ordinary Cargo elapsed time and hardware retired instructions were outside this experiment.

A real signed Rust `#[track_caller]` function crossed a C identity function as an opaque function pointer and was called again by Rust. Moving its definition by four lines changed its observed result from 5 to 9, and the full LLVM keys differed. The direct and observation builds gave byte-identical native programs within each version. Nineteen controls refused unsupported inputs, including inline/module assembly, sanitizer or profiling state, embedded source, semantic metadata referencing a debug location, and the actual LLVM merged-location flag. A cross-file transition from equal lines 70/70 to 70/71 misses; 70/71 to 70/72 qualifies. Ordinary LLVM can mark those instruction boundaries differently. Materialized caller coordinates remain ordinary data.

The record covers one compiler, one x86-64 ELF/DWARF configuration and one real edit. An integrated compiler also needs an independent validated native output reader. Reusing a key on a compiler miss must preserve ordinary machine code and debugging behavior. Opt-in sample PGO uses relative source line distances, which the key does not preserve. The reader conservatively rejects this mode.

## Reopen

`verify.py` checks all 66 individual Callgrind streams, five disjoint call edges, each original module/key binding, current wire hashes, field-preserving inverse controls, and the original budget. The packaged traces retain every event and call edge. Physical filesystem paths in their headers and file labels were replaced with hashed labels; the observations also commit to each unmodified private raw file.

```sh
python3 -IB verify.py
```

To rerun, supply the original archive, the signed LLVM library and matching LLVM headers, plus Clang and the standard Valgrind development headers. The archived actor used Clang 18.1.3 and Callgrind 3.22.0. An added `--price` records all three counter regions for every edited unit.

```sh
LLVM_CONFIG=/path/to/llvm-config SIGNED_LLVM=/path/to/libLLVM.so.23.1-rust-1.99.0-beta OUT=/tmp/native-reader sh build.sh
python3 -IB replay.py --reader /tmp/native-reader/reader --capture /path/to/ordinary-13109144871.zip --out /tmp/ruff-cgu-replay
```
