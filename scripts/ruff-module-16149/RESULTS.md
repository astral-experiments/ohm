# The private-module edit still rebuilt the same six rustcs

On the original three-file edit in Ruff #16149, both compilers rebuilt the linter, graph, workspace, server, and both Ruff library and binary. Both following unchanged checks launched zero rustcs. The experiment stopped at this workload-shape gate. It has no instruction-count or wall-time claim. [Complete original run](https://github.com/astral-experiments/ohm/actions/runs/41576771221)

| Actual ruff_linter metadata after the edit | Parent | Candidate |
|---|---:|---:|
| Changed, added, or removed published local rows | 25,924 | 20,440 |
| Indexed expansion rows whose values differed | 882 | 882 |
| Loaded external dependency bindings that differed | 0 | 0 |
| Stable definition identities whose presence or definition changed | 5 | 5 |

The helpers module was still published on the candidate in both source states. Its row changed from `f85de66bf652b83a3734d0d0eef3c31d` to `3fa9d8b60fb682f166a604828d6f7a49`. All five fields of `SequenceIndexVisitor` still pointed to the helpers module in the embedded type and direct visibility table. The module itself changed from restricted to `rules::pylint` to restricted to the crate. The selected private helper functions had no published rows, optimized MIR, or CTFE bodies. Each compiler's full producer public hash changed across the actual edit.

All eight independently built CLI states passed the three native controls. The real `__add__` edit switched on PLW3201 with the expected message, and Ruff's upstream fix switched it off. Each edited CLI matched its own clean executable byte-for-byte. Both compilers produced the expected E0308 for the invalid source, and every selected crate's edited public, global, and stable hashes matched its repaired and clean controls. The restored syscall-observed edit reproduced the ordinary Cargo roster; it differed in the linter's complete metadata bytes. Both arms' identity gate records that discrepancy, and the primary public-hash and work-roster gates independently decided the experiment.

The compact record contains the complete native executable hashes, all selected original metadata hashes, compiler identities, scope witnesses, and decoded counts. The transport holds 24 distinct complete metadata files. Its 62,490,278 bytes have SHA-256 `0440fef9e654c08644b68b4bce49405c02c276a20de3e8fbff8bf0d367e310ba`. The previous refusal, archive identity, and its independently passing controls are preserved as well. [Compact original projections](results.json) · [Source and predeclared workload](README.md)
