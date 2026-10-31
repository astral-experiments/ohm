# Native admission for mixed-profile generic sharing

The subject is the thirteen-file diff from Ohm Rust #251 (`424df60a2d746ecd35bbf0cc68cf91c06c6ac465`) to `7562c319cd9dbd3c1aa99a5797638d05c2026fff`.
`source.py` independently transplants the feature onto published -21 Rust `c79998a5cd143c445a4b2528f20953b176a65c5d`. Twelve files apply directly without three-way resolution. The incremental-format file already used generation 8 on signed Rust and generation 4 on #251. Registration checks every other byte in that file and requires the two patched versions to have identical generation 9 contents. The resulting full Git tree is `0d30133a68ccfb5771670ef5fee7720e1483f5dc`, with compiler subtree `bf2496d480b3e17e3b4c929d41bf765a5cef889d`. The signed canonical full-index patch SHA-256 is `75023f3a01039cc590a1583c0e7ac78e2b7e4b661f82e98e736bd2b3c63c0898`. `source/product.json` records every before/after blob on both bases. There are no Rust product refs in this QA repository.

The two compiler arms use the same upstream 1.99.0, bootstrap binaries, CI LLVM key, source/build path, x.py options and `-j8`. Each arm uses its own stage1 compiler and every member of its own x86_64 GNU standard library. Both receive the existing strict Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd` (ELF SHA-256 `035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4`) and signed -21 Wild (SHA-256 `0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5`). Every transferred member is reopened and hashed on a different machine.

A third, independent bootstrap uses the genuine original head of #220, `5e95666f875d0886e541650fa2807ed23ce501c6`. It has the original one-byte Boolean in the correct record position and the bare metadata stamp. It uses the same std sources, stage0 and LLVM as the two main roles. Each reader must successfully execute an application that imports the old producer from this complete, selected sysroot and retains the old externally shared generic. It must reject these same old user artifacts outside that sysroot, and reject user metadata from the opposite epoch, with normal `E0514` errors. Official 1.99.0 builds and runs its own program. Its release version stamp differs from the tested omit-git-hash stage1s and must be rejected cleanly by both. We never edit library metadata to manufacture compatibility.

The collector explicitly exercises the persisted native incremental graph in both directions under one forced graph stamp, while requiring naturally identical complete stage1 `rustc -vV` results. The compiler must reuse its own graph and refuse the opposite generation. An independent reader checks the recorded RSIC headers, previous metadata-prefix files, raw `.rmeta` and diagnostic/native results. The separate ordinary Cargo migration below uses no forced stamp.

The candidate runs the repository tests `rmeta::generic_export_flags_preserve_old_c_linker_bits` and `tests/run-make/ohm-profile-aware-shared-generics`. The collector then captures both sides’ function-pointer LLVM symbols, debug assertions, overflow panics, UB checks on defined Rust input, and operating-system process statuses. A no-core fixture uses the Rust repository’s unmodified minicore to compare native x86_64, cross AArch64 and a custom JSON target with the exact host name. Only the builtin native target may move the generic. The same-target Cargo test flips the producer between O0 and O1 and back, changes the returned value, introduces a real `E0308`, then repairs the source. Empty targets independently verify each output and failure. Runtime harness execution is for correctness only. This workflow has no perf counters or release steps.

The earlier source build used the same x.py bootstrap method and native Namespace 16-core Linux hosts. Reserve three independent machines with at least 32 GiB free disk and 6 GiB available RAM each, followed by a smaller native collector. Prior host plus cross builds and real Ruff verification took around 11–14 recorded job minutes. The new unit and legacy jobs have no measured completion time yet. [Earlier source run](https://github.com/astral-experiments/ohm/actions/runs/41129270278)

## Local source verification

With a Git object store containing the public upstream and the previous Ohm source transport, run the following in the packaging checkout. `audit.py` reopens each pack independently and verifies its complete object membership, thirteen signed-source after-images and full transplanted tree.

```sh
python3 -IB scripts/strict-mixed-generics/audit.py /absolute/path/to/ohm-rust/.git
```

The previously qualified single strict Cargo artifact expires on 2026-11-01 at 00:40:29 UTC. After that, rebuild the **same** executable using the original signed-package build recipe and source inventory and verify the whole ELF hash above before supplying it in place of the retrieval step. The current workflow deliberately stops if its pinned artifact has expired. [Original strict build recipe](https://github.com/astral-experiments/ohm/blob/f23a67771c625785cd70f58e9b46e8d26af3d317/.github/workflows/ci.yml) [Prior Cargo build](https://github.com/astral-experiments/ohm/actions/runs/41151297839)

## Later workflow admissions

Hold the historical Ruff performance cohorts until native admission and the product bridge pass. On pinned Ruff `9352615`, test the actual `cargo +ohm test --no-run -p ty_server --test e2e` target, capture physical linker and rustc execs, and inventory the hash and `--list` entries of the native test artifact. Apply the complete eight-file Ruff commit `4d6a7db787130c5a4a95bd835369babd78e4a1f6` in reverse with `git apply --check -R`. The exact 13,226-byte patch SHA-256 is `f5a3c6085bb0e90335c5f1686a0eb9c61e1456aa5d5808381a2deea304b3650d`. Confirm the native relink and the removal of the real `notebook::cells_after_cell_magic` case against independent clean output. Restore the edit and check the restored native link and list against a second independent clean. Test execution and list collection are excluded from any measured window.

### Compiler upgrade on populated targets

Validate actual Cargo migration separately from toggling an existing producer profile. Enroll these three disjoint same-path installations and their independent clean counterparts before querying results.

| Initial and subsequent toolchain at the same Cargo/rustc pathname | Question |
| --- | --- |
| Matched stage1 parent to stage1 candidate | The deliberately identical `rustc -vV` text with different compiler and metadata epoch exposes implicit identity assumptions. |
| Matched stage1 parent to a reinstallation of the exact parent bytes | Fresh inodes and controlled installation timestamps distinguish reinstall work from product/epoch work. |
| Signed -21 compiler and standard library to the candidate | Record actual differing version text and physical code, with the same strict Cargo ELF and signed Wild on both visits. |

Populate the real history with the unmodified Ruff project, private target and distinct shared build directory. Keep their filesystem paths, inodes and data. Replace the full SDK and standard library through the same stable install path. For the sham, copy the original bytes to fresh inodes using the same installation clock/path procedure. Capture `stat`, `rustc -vV`, `cargo -vV` and hashes of compiler, driver, standard libraries, Cargo and Wild before/after. Do not inject flags to manufacture an identity change and do not clean the prior state.

Record each first unchanged and second unchanged visit, a real source edit, the accepted clean result, a real malformed compile and repair. Require exact program/list output, Cargo's terminal JSON status and diagnostics versus separate empty targets for the same state and toolchain. Preserve any E0514 or unexpected success on a valid input, even if a manual clean recovers it. Capture actual rustc/Wild invocations including link-only visits and pre/post allocated `st_blocks * 512` for target plus shared data, deduplicating `(st_dev, st_ino)` globally. Exclude every SDK and temporary receipt. Publish the first migration cost, retained storage and ordinary repeat separately. No low-migration-cost or release-compatibility claim is made by this native admission.
