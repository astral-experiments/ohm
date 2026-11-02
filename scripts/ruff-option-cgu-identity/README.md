# What changed in the 21 Ruff option codegen units?

Inserting four lines into Ruff’s option documentation regenerated 21 units in an ordinary signed Ohm -22 incremental build. Nineteen units have identical allocated object contents, symbols and every resolved relocation. Four of those nineteen are already identical as complete ELF files. The other fifteen differ only in debugger data. The two remaining units have genuine runtime changes. [Ruff edit](https://github.com/astral-sh/ruff/pull/28106) · [Original capture and native oracle](https://github.com/astral-experiments/ohm/actions/runs/41371190920)

| Original codegen inputs | Units | IR optimization, guest Ir | Machine emission, guest Ir |
| --- | ---: | ---: | ---: |
| All regenerated units | 21 | 39,954,986,517 | 80,951,283,935 |
| Already identical after ordinary debug stripping | 8 | 4,521,051,742 | 10,904,178,903 |
| Further units with moved, unobserved caller-location operands | 11 | 33,268,172,412 | 66,169,519,459 |
| All nineteen with equal allocated objects and relocations | 19 | 37,789,224,154 | 77,073,698,362 |
| Genuine runtime changes | 2 | 2,165,762,363 | 3,877,585,573 |

These counts come from two disjoint calls in the archived fixed-input backend actor. They measure the pipeline that ran. A future implementation still has to construct and validate the key, materialize current debug information, and pass whole-Cargo comparisons. The source-eligibility experiment below generated no machine code and established no whole-command speedup.

## What accounts for the nineteen?

Eleven objects change both `.debug_info` and `.debug_line`, three change only `.debug_info`, and one changes only `.debug_line`. Every one of the 16,560 differing line-program rows and 11,474 differing inlined call-line attributes moves forward by four lines in `crates/ruff_workspace/src/options.rs`. They account for all 36,326 differing object bytes. These nineteen objects contain 11,380 subprogram entries and 37,650 inlined subroutine entries. The complete edited object equals an independently empty build for each of the 21 units.

All 14,167 named function definitions have identical IR after removing debugger metadata. In eleven of the nineteen, 190 immutable caller-location constants contain a genuinely different line number. All 3,022 uses directly call or invoke one of thirty internal monomorphizations of `Result::from_residual`. The final formal has zero ordinary IR uses. Across the 21 surviving post-O1 snapshots, all 190 module-local instances of those callees disappear. Only two archived pre-optimization inputs were identical in both histories. The other nineteen OLD inputs lack an independent post-O1 capture.

For the comparison only, we canonicalized the numerical line in a literal whose uses were all proven to pass to that unused local formal. Separately, for every logical debugger file, we assigned positive line numbers their ordinal in the input module’s sorted distinct lines. Zero, columns, files, lexical scopes, inline chains, discriminators and the remainder of the module stay visible to LLVM. The current file checksum is checked against current source bytes and carried with those coordinates. Inverting each input’s own ordinal map reproduced its original debug metadata exactly. The result was nineteen byte-identical complete LLVM bitcodes. Keeping the actual edited file’s MD5 in the machine identity admitted just two.

The comparison of unused formals is specific to these archived inputs. A compiler implementation must establish legality for metadata-only uses, argument attributes and special calling conventions, or use LLVM’s own semantics-preserving passes on the module it will compile.

The data-only counterexample retained a direct call to `log::__private_api::loc`, with line 3041 becoming 3045 at column 21. The other counterexample changed the option text, its length, and machine instructions. Both pairs remained distinct. As a separate check the real signed LLVM `deadargelim,globaldce` passes on one of the eleven removed all 25 moved, unused locations and produced the same comparison bitcode. The passes kept the two genuine changes distinct, including the observed logging location.

Existing Ohm Rust work preserves constant allocation identity, generic-provider dependencies, coroutine metadata and cross-crate source coordinates. The moved constants here have different values. Passing a source location through a function pointer or exposing the new option string must continue to produce the current value. [Constant provenance](https://github.com/astral-experiments/ohm-rust/pull/318) · [Generic providers](https://github.com/astral-experiments/ohm-rust/pull/329) · [Coroutine debug locations](https://github.com/astral-experiments/ohm-rust/pull/132) · [Cross-crate location regression](https://github.com/astral-experiments/ohm-rust/pull/245)

## Reopen the evidence

Run with Python 3.11 or newer on any host for the compact check.

```sh
python3 -IB verify.py
```

For the raw comparison, use the original compressed artifact, the signed Linux x86-64 -22 SDK's LLVM 23 shared object, and a Ruff checkout containing the edit and its parent. The verifier checks the archive and LLVM SHA-256, the two source bodies, all 63 complete ELF objects, every old/new pre-optimization input, the full LLVM keys, and the six real dead-argument transformations. Supplying two source files via `--source-old` and `--source-new` works without a Git checkout. The two roles derive their coordinate tables independently. This replay reads each input in place.

```sh
python3 -IB verify.py --capture /path/to/ordinary-13109144871.zip \
  --llvm /path/to/libLLVM.so.23.1-rust-1.99.0-beta \
  --ruff-checkout /path/to/ruff
```

The original physical command used `-Copt-level=1 -Clto=off -Cembed-bitcode=no -Cdebuginfo=line-tables-only` and incremental compilation. Its additional observation pass retained bitcode via `-Csave-temps=yes`. The native results include both edited warm and independently empty outputs. The full `.bc` files and diagnostic object captures are research inputs outside an ordinary incremental work product. The compressed ordinal files here are audit data that permit independent reconstruction of the key. They are not a proposed work-product size.

The two SHA-256 bound roles in `ordinal-tables.json.gz` refer to Ruff source commits. `ordinal-file-signatures.json.gz` preserves each module’s original LLVM-declared per-file checksum kinds and values. `receipts.json.gz` contains all 21 source and output identities, per-unit instruction edges, semantic checks, and the two counterexamples.
