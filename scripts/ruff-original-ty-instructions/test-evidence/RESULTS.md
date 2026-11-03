# Ruff linter test-build confirmation

For Ruff's original RUF009 fix, accepting register-only x86 `sete` in Ohm rustc reduced the first unchanged `cargo test --no-run` from 55.30 billion to 409.21 million retired user instructions. Six independently booted Linux runners recorded a median paired reduction of **99.2601% (135.15×)**, with a 96.875% median interval of 99.2593–99.2601%. The real edit cost **29.2333%** fewer instructions, with an interval of 29.1782–29.2880%. Both two-sided paired sign tests give p = 0.03125. Each runner produced the same complete expected native executable for each source state. [Preregistered six-pair study](https://github.com/astral-experiments/ohm/actions/runs/41615000072)

| Rank | Order | Edited P | Edited C | First unchanged P | First unchanged C |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 | PC | 55,705,277,509 | 39,451,466,143 | 55,295,766,315 | 409,146,024 |
| 1 | CP | 55,744,753,798 | 39,446,624,779 | 55,253,899,179 | 409,231,737 |
| 2 | PC | 55,697,024,868 | 39,408,037,762 | 55,313,960,535 | 409,265,689 |
| 3 | CP | 55,742,620,333 | 39,449,323,374 | 55,305,580,048 | 409,190,760 |
| 4 | PC | 55,742,360,313 | 39,416,539,434 | 55,241,250,421 | 409,179,324 |
| 5 | CP | 55,730,660,709 | 39,454,801,017 | 55,305,281,242 | 409,224,094 |

P is the release-23 Rust source `d57fd1515986dccecdcece8da85e651bfb4b81f9`. C is `a65831c7215662f270cd95a760b7163399835269`. Both normal-layout SDKs came from the same compiler factory. They use the same Cargo, Wild, LLVM and standard-library inputs. The original Ruff edit is `710c60f7135879b05f6c05a34085cd7af5c19e7f` to `b00f68a23cedbd3a38fc25bac63638f0f11fc3f0`. The private Cargo home contained all 445 original checksummed registry packages and the original pinned Git dependencies. The locked `portable-atomic` 1.11.0 uses `sete cl`. Ruff main at `08cab22a1599a9f16d0cb4ceaef56a138603a6da` locks 1.13.1, which uses the already-supported `setne cl`. [Ruff edit](https://github.com/astral-sh/ruff/pull/19021), [compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41605530113), [prior assembly support](https://github.com/astral-experiments/ohm-rust/pull/267)

### What Cargo did

Each host ran one counterbalanced P/C pair with an unmodified working tree, stable paths, ordinary compiler flags and a private Cargo home. A pinned hardware counter included the untraced Cargo command and all its descendants. All clocks had identical enabled and running counts. Each arm started cold on OLD, switched to the real edit, ran four unchanged builds, rejected an ill-typed Rust edit with E0308, repaired it, and produced an independent empty-target build of NEW. A separate repetition recorded physical execs, actual linker arguments and native inputs outside the measured history. All test executions were outside the counter.

* On the edit, P ran four rustcs for `portable_atomic`, `salsa`, `ruff_db` and the `ruff_linter` test. C ran just `ruff_linter`. Both executed Wild.
* On the next unchanged command P ran the same four rustcs and Wild. C launched zero rustcs and zero linkers.
* Subsequent unchanged commands gave paired median instruction ratios of 140.79×, 134.18× and 134.75×. These are repeated observations on the same six runners. The independent cold NEW median was 0.0029% more instructions on C. Cold OLD was 0.0044% fewer.

### Native and source controls

All hosts and arms reproduced the same OLD executable of 91,981,320 bytes (`b997eca0512b61cdd0bd04230155fc73622f16c5df66fbaf6ac62310ac39b886`) and NEW executable of 91,981,664 bytes (`75b1dc527baeec4b501c69b818a6fc7100dcfdd57309ea6af2f72f6e902713fa`). The independent reader reopened 497 independently addressed native files on every worker, including the whole harness and the archived inputs to the real Wild invocations.

Each native executable listed the exact same 2,454 test names. The selected RUF009 snapshot test passed on OLD, edited NEW, repaired NEW and independently clean NEW. Running the withheld OLD harness on the genuine NEW fixture and snapshot failed with the missing `list()` diagnostic at line 144 and the unwanted `attr.field` diagnostic at line 134. The ill-typed Rust source made Cargo exit 101 with E0308 and zero accepted test executables. [Matched runner and pinned behavior](../native_test.py)

### Storage

P and C each retained 5,015 physical files at the end of the warm history. Counts and total bytes of `.o` and `.rlib` matched. Both retained one `.rlink`, and C's was 336 bytes smaller. C used 3,063,048–3,130,836 more logical bytes across the two Cargo directories (3,055,616–3,129,344 more allocated bytes). C kept the original `ruff_db` incremental query cache, whose existing file was 3,155,337–3,155,801 bytes larger than the cache rewritten by P. Changes in the other incremental files offset part of that increase.

An earlier six-host confirmation was rejected and excluded in full. Five redundant P compiles rewrote one Salsa metadata file 12 bytes larger. Both sizes already occurred on the same compiler in two independent native CLI controls. The replacement registration froze both precise sizes, retained every original Salsa metadata byte and required all other 215 metadata filenames and sizes to match. The earlier discovery run also contributes zero pairs to these estimates. [Excluded confirmation](https://github.com/astral-experiments/ohm/actions/runs/41612100844), [its archived storage and native readback](previous-cohort.json), [separate discovery](https://github.com/astral-experiments/ohm/actions/runs/41610426866)

All 36 retained fresh Salsa sidecars decoded against the source-bound compiler schema. Every sidecar matched its arm's cold private, public and global crate hashes, all 5,288 definition identities, 4,142 per-definition RDR hashes, 854 expansion rows, and 56 required dependency hashes. Every sidecar had 979 populated entries in `CrateRoot.syntax_contexts`. Four redundant parent compilations crossed from 48 to 49 sparse index buckets, each exactly 12 bytes. The other two stayed at 48. Full physical sidecar lengths were 1,979,164 or 1,979,176 bytes and all occupied 1,982,464 bytes on disk. [Per-file native evidence](hygiene-table.json), [compiler sparse-table layout](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_metadata/src/rmeta/table.rs#L16-L20)

### Reproduce

The recorded workflow command is `cargo +ohm test -p ruff_linter --lib --no-run --locked --offline -j4`. Print the paired statistics from the compact original counter records with the following command.

```sh
python3 scripts/ruff-original-ty-instructions/test-evidence/verify.py
```

To reopen the original native files while the hosted evidence remains available, download the six ZIPs into `0/original.zip` through `5/original.zip`, as listed in `pairs.json`. Run the same script with `--archives <directory>`. This mode requires `zstd` and the Git object for the registered compiler decoder at `dba43a0fb9e924785ec8196f166b780c73564589`. To run the actual six-host study again, use the exact registered nonrelease workflow.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-historical-ruff-sete-test-v2-20261103 \
  -f reviewed_head=262ae0b6f4c035874bf295b398c11f9374c03c46
```

[pairs.json](pairs.json) contains the six immutable original ZIP IDs and digests, both source identities, actual kernel boot and runner IDs, the original 84 process-tree clock records, all disaggregated storage totals and typed Salsa results.
