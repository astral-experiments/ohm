# Reconstructing Ruff #28106's debug locations from the prior native object

For 19 of the 21 `ruff_workspace` codegen units rebuilt after this edit, an Old-only reconstruction reproduced the complete native ELF from the incremental New build and an independently empty New build. Fifteen required new debug locations and four already matched. The program re-encoded 16,560 address-to-line rows and 11,474 inline call-site lines. LLVM's ordinary machine code, symbol table, relocation records, section offsets and all remaining bytes came from the Old object. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41371190920) · [Ruff source comparison](https://github.com/astral-sh/ruff/compare/3c77dcc2a5c04fc0c54ce95cd51068734015f3e0...088b7b5f77fcb05994fd2a17cbc940cd9edb341a)

The other two objects show why debug reconstruction needs a separate semantic eligibility test. `5sv44via3t35z6qtc7x39769v` contained changed machine instructions. The encoder also refused it because the remapped line-program layout moved a relocation. `b8uuib8od83lhvdebd58dtnlh` produced a well-formed debug rewrite but retained a stale 24-byte allocated Rust `Location` constant. Both independent New builds agreed on the correct native contents of these objects.

## Inputs and custody

The roster covers all 21 reoptimized codegen units observed in this edit. The predictor initially opened only the Old archive from job artifact `13109144871` and `options.rs` at the two actual Ruff revisions. The two source hunks inserted two complete lines each. Every one of the 4,570 Old source lines was byte-identical at its New position, including its columns. The file-qualified mapping left the remaining source files untouched.

The predictor SHA-256 sealed before opening either New native archive was `ded3f5947b96cb4be3ea5d3894c27b9f7afa1e77f1b1cacbf2064d563d5c8b62`. The compact packet contains that exact JSON, the independently computed warm and empty native digests, the original predictor sources, four Old objects, and the Old source with its two insertion hunks. It contains no New object bytes. The full historical artifact SHA-256 is `53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b`.

The ELF reader accepts x86-64 relocatable, little-endian DWARF4 line tables and a limited set of source-bearing Rust DIEs. It verifies each Old line program's canonical encoding, preserves column and discriminator state, and rejects any change of section width or `set_address` relocation offset. The frozen controls rejected a missing source line, a same-line edit affecting column bytes, a mismatched absolute source path, a missing line-table file, a variable-bearing DWARF abbreviation and a remapping that crossed an encoding-width boundary. [Matching LLVM line-program emitter](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/MC/MCDwarf.cpp)

An independent LLVM debugger decoded every accepted Old and reconstructed object. It compared 124,357 rows at their real text-symbol-relative instruction addresses, including 119,233 nonzero column numbers, and the complete Rust DIE dump. Exactly the same 16,560 rows and 11,474 call-site attributes moved.

## Reproduce

Python 3.11 or later and its standard library suffice. From this directory, replay one reconstructed object, one identical object, the actual allocated-data counterexample and the refusal.

```sh
python3 -IB verify.py
```

To repeat all 21 whole-ELF byte comparisons, add the original artifact ZIP.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13109144871/zip > ordinary-13109144871.zip
python3 -IB verify.py --original ordinary-13109144871.zip
```

This is an object reconstruction experiment. It prices neither complete Cargo commands nor an implemented compiler fast path. The ordinary incremental `SourceFile` stores a hash and positions, and its deserializer sets the source text to `None`. Obtaining a prior-to-current mapping without assuming a VCS checkout is a separate implementation requirement. [rustc source-file serialization](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_span/src/lib.rs#L1993-L2103) · [LLVM debug source embedding](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_codegen_llvm/src/debuginfo/metadata.rs#L612-L629)

The separately frozen compiler-input study checks the complete pre-optimization module key and reprobes both native counterexamples. [Independent compiler-input evidence](https://github.com/astral-experiments/ohm/tree/fda8bcd899ec1843839c350c118d556af75710fe/scripts/ruff-option-cgu-identity)

LLVM also compares consecutive physical line numbers when computing `is_stmt`, including across file boundaries. A source edit can change that comparison even when both per-file coordinate ranks remain stable. A general compiler path needs to preserve or reconstruct that decision. The 19 byte comparisons above establish the result for this specific cohort. [DWARF statement emission](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/CodeGen/AsmPrinter/DwarfDebug.cpp#L2286-L2312)
