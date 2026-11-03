# A fully empty native Ruff build reproduced each edited executable

Each role started from an empty target and build directory on the actual parent of Ruff #19021, then built the original three-file fix, repeated the build, reversed the edit, compiled an intentional error, repaired it, and independently built the fix from empty. The command was ordinary `cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json`. Both toolchains included the #347 input writer, #349 assembly rule and the same Cargo with the guarded private-derive negotiation. The child also contained the private-derive compiler change. This study recorded native behavior. [Frozen study and source identities](https://github.com/astral-experiments/ohm/tree/6cfeb854f07e6e24bfbe450cca8b79fdc7afd583/scripts/ruff-ruf009-derived-enum) · [Original worker](https://github.com/astral-experiments/ohm/actions/runs/41625608181)

| Native ELF | Buggy | Fixed |
| --- | --- | --- |
| Parent | `35ef8e091d84…` | `6a9d1f5630e6…` |
| Child | `f058a81e2227…` | `637b41739193…` |

Every successful visit matched the complete executable from that role's independent build of the same source. Four actual CLI inputs on each of 12 successful visits produced the expected 48 RUF009 outcomes, including the test that stops reporting and the test that starts reporting. Both intentional Rust errors emitted E0308. Six kernel traces show actual ty_python_semantic, ruff_linter and ruff rustcs after edits, and ty_python_semantic and ruff on the unchanged build. The compiler raw depfiles for portable_atomic and salsa were reopened alongside their translated Cargo records.

Across compilers, all native machine-code and data bytes matched. The only differing bytes were in three DWARF sections and the GNU build ID. The reader verifies the two actual Cargo-generated jemalloc build directories, decodes every affected DWARF form, checks the byte-level section boundaries and rechecks the Wild build IDs. The independently empty BUGGY and FIXED images each contain millions of debug lines. All four complete ELF digests and both sets of stream hashes are in `verified.json`.

The original archive (artifact 13225534668) is SHA-256 `2560c343601f78dba0aa777ca2af304ba849e835da58495c7db3436ec8355886`. This directory contains its original runtime, typed Cargo output, raw kernel trace and physical inventory records. The exported ELF bodies are reproduced with lossless zstd deltas against the exact base in the adjacent seeded-history packet. The four deltas total 39,792,758 bytes and reconstruct 671,681,232 bytes. The archive's large intermediate dependency blobs are listed by digest. The complete archive is also held separately under its physical SHA. This history and the earlier seeded refusal have separate receipts. [Earlier refused history](../evidence-native-cases-41623337781/README.md)

From the packaging checkout, with Python 3.11+, zstd, b3sum, llvm-dwarfdump-18 and at least 3 GiB of temporary disk space, run

```sh
python3 -IB scripts/ruff-ruf009-derived-enum/evidence-empty-native-41625608181/verify.py --out /tmp/ruf009-empty-native-verified.json
```

The fixed-name verifier checks its own SHA table, reconstructs and hashes every ELF, and reopens the native verdicts, kernel argv and decoded sections. It records the SHA of each complete unnormalized decoded stream under a stable filename. For comparison to the original random temporary filenames it separately checks the first filename line printed by llvm-dwarfdump, every subsequent canonical byte, and the exact raw byte count after accounting for the filename length. The native bytes are compared directly throughout.
