# Preserve cross-file line comparisons when moving DWARF locations

LLVM compares the current line number with the preceding nonzero line number when deciding whether an instruction begins a source statement. Two locations in different files can therefore affect one another. Moving an instruction in `b.rs` from line 70 to 71 changes its statement flag when it follows line 70 of `a.rs`. The machine instructions, column, lexical scopes and per-file ordinal positions all stay the same.

The fixture passes the same LLVM IR to the signed Ohm `-22` LLVM library with three values for that one line number. Each object contains the same 15 bytes of x86-64 machine code. Every executable returns `19 19`. Starting GDB at `probe` on `a.rs:70` and issuing one `step` distinguishes the artifacts.

| Object | Row at `probe+6` | GDB stops after one step |
| --- | --- | --- |
| LLVM output with `b.rs:70` | `b.rs:70`, statement flag clear | `a.rs:91` at `probe+12` |
| LLVM output with `b.rs:71` | `b.rs:71`, statement flag set | `b.rs:71` at `probe+6` |
| Original rewriter applied to 70→71 | `b.rs:71`, statement flag clear | `a.rs:91` at `probe+12` |
| Original rewriter applied to 71→72 | `b.rs:72`, statement flag set | `b.rs:72` at `probe+6` |

The verifier also checks both reverse edits. It rejects 70↔71 and admits 71↔72 by preserving the order and equality of physical line numbers across **all** files in the codegen unit, fixing lines zero and one. Both admitted rewrites match the entire independently emitted object. The seven executions and GDB stops are recorded in [`verified.json`](verified.json). The implementation that decides the statement flag reads `DL.getLine() != OldLine` in `DwarfDebug::beginInstruction`. [Pinned LLVM source](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/CodeGen/AsmPrinter/DwarfDebug.cpp#L2293-L2299)

On the real Ruff option edit, 19 of 21 recompiled units previously matched their warm and independently clean native objects after source locations were rewritten. The global order check admits 15 of those 19. The 15 represent **83,908,903,279 of 120,906,271,208 LLVM guest instructions (69.400%)** in the fixed-input backend replay. These are retrospective costs for the admitted work. A whole-Cargo hardware measurement still requires an integrated compiler. [Original input and costs](https://github.com/astral-experiments/ohm/tree/fda8bcd899ec1843839c350c118d556af75710fe/scripts/ruff-option-cgu-identity) · [Original native reconstruction and clean comparison](https://github.com/astral-experiments/ohm/tree/e9bcd74aea3dfedd528d11dec2a9d9d228a7a9b0/scripts/ruff-cgu-debug-locations/evidence/41371190920)

## Reproduction

Use Python 3.11+, a GNU C compiler and binutils, `llvm-dwarfdump-18`, GDB and the signed GNU `-22` `libLLVM.so.23.1-rust-1.99.0-beta` with SHA-256 `43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51`. Run this from the evidence directory in a checkout containing the two linked Ohm evidence commits.

```sh
qa_dir="$(mktemp -d)"
git show e9bcd74aea3dfedd528d11dec2a9d9d228a7a9b0:scripts/ruff-cgu-debug-locations/evidence/41371190920/patch_dwarf.py > "$qa_dir/patch_dwarf.py"
git show fda8bcd899ec1843839c350c118d556af75710fe:scripts/ruff-option-cgu-identity/ordinal-tables.json.gz > "$qa_dir/ordinal-tables.json.gz"
python3 -IB verify.py --debugger --llvm "$OHM_SIGNED_LLVM" \
  --patcher "$qa_dir/patch_dwarf.py" --tables "$qa_dir/ordinal-tables.json.gz" > "$qa_dir/verified.json"
diff -u verified.json "$qa_dir/verified.json"
```

Omit `--debugger` on a host that cannot trace its own child processes. The verifier still checks the raw statement flags, native executions, whole-object equalities, input digests and instruction-count sum.
