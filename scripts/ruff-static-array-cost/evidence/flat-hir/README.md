# Flat HIR node types on the Ruff Unicode edit

**Hold a separate compiler PR.** Representing consecutive integer-literal HIR nodes with one type passed the preregistered 5% check-compiler threshold. It saved 5.3239% of the selected rustc and 1.1514% of the complete edited Cargo check. The unrelated Ruff AST check showed no material saving. These results price the change on top of C5, the compiler used in the existing bulk-lowering PR. The size of the whole-workflow gain does not justify a global incremental-format change for this campaign. [Bulk-lowering PR](https://github.com/astral-experiments/ohm-rust/pull/353)

## Real edit and measurements

An actual Ruff dependency and generator update changed the emitted Unicode tables. Cargo checked or built the original Ruff package and its locked dependencies. Each arm had its own cold OLD, edited, settled and independently empty NEW history. An independently observed build of the same edit supplied the selected rustc’s full exec-to-exit hardware counter. The ordinary Cargo command was measured separately. The counters are unscaled retired user-mode instructions. [Ruff edit #29261](https://github.com/astral-sh/ruff/pull/29261) · [Frozen selection and thresholds](../../registration.json)

| Six new boots | Median reduction | Minimum to maximum |
|---|---:|---:|
| Edited check, entire selected rustc | 5.3239% | 5.3183% to 5.3511% |
| Edited check, complete Cargo | 1.1514% | 1.1146% to 1.2142% |
| Edited build, entire selected rustc | 4.7774% | 4.7185% to 4.8181% |
| Edited build, complete Cargo | 1.1245% | 1.0738% to 1.1942% |
| Independently empty check, selected rustc | 5.3347% | 5.3251% to 5.4260% |
| Independently empty build, selected rustc | 4.7961% | 4.7587% to 4.8215% |
| Unrelated Ruff AST, whole cold check | 0.0172% | 0.0015% to 0.0247% |
| Unrelated Ruff AST, whole settled check | 0.0299% | -0.0125% to 0.0780% |

Each primary pair favored C6. The exact two-sided sign-test p-value is 0.03125. With six independent pairs the sample minimum and maximum give a 96.875% distribution-free interval for the population median. The two independent pilot boots passed 5% before confirmation. Neither study triggered the preregistered cold or settled veto of a consistent increase above both 5% and 10 million instructions. The unrelated AST veto used both 2% and 10 million. That control built the same 39 units on cold and zero on settled for every arm. [Complete paired counts](counts.json)

| Cohort | Order | C5 edited check rustc | C6 edited check rustc | Reduction |
|---|---|---:|---:|---:|
| pilot CP | CP | 5,775,727,206 | 5,467,109,514 | 5.3434% |
| pilot PC | PC | 5,776,526,622 | 5,466,948,704 | 5.3592% |
| confirm B1 | CP | 5,775,378,723 | 5,466,689,383 | 5.3449% |
| confirm B2 | PC | 5,773,981,313 | 5,466,782,026 | 5.3204% |
| confirm B3 | PC | 5,774,622,904 | 5,467,292,419 | 5.3221% |
| confirm B4 | CP | 5,776,546,242 | 5,468,899,441 | 5.3258% |
| confirm B5 | CP | 5,775,650,528 | 5,468,485,953 | 5.3183% |
| confirm B6 | PC | 5,775,140,108 | 5,466,108,267 | 5.3511% |

P is C5 and C is C6. All eight boot IDs are distinct and separate from the previous C5 study. The first attempted confirmation had an isolated-Python import failure. Three jobs failed and the other three were cancelled. Its entire cohort was excluded before opening any performance result. The corrected registration changed the AST control import path. [Opposite-order pilots](https://github.com/astral-experiments/ohm/actions/runs/41747290958) · [Excluded setup](https://github.com/astral-experiments/ohm/actions/runs/41749941054) · [Six independent pairs](https://github.com/astral-experiments/ohm/actions/runs/41750680580)

## Compiler and behavior

C5 is `6c2874a0b6a0bf3570f8959733b6f87907e5cce6`. C6 is its direct child `65390392975bd2668748fd8bd8ebc52915772f41`. Both inputs are the candidate role of a separate stage-1 rustc factory, built with the same bootstrap command and Cargo. The original qualification archives, exact source trees and five changed blob pairs are included here. The local physical driver ELF sizes were 142,979,024 and 143,010,520 bytes. Each matched the SHA-256 in its own factory and all eight measurement packets. [C5 factory](https://github.com/astral-experiments/ohm/actions/runs/41738460962) · [C6 factory](https://github.com/astral-experiments/ohm/actions/runs/41743833358) · [Physical source identities](sources.json) · [Exact source delta](source.patch)

The change replaces individual HIR-to-type entries with a single inclusive range and a shared type when the literal IDs belong to one owner, are consecutive and have no conflicting entries. Out-of-range requests use the normal table. An overlapping write or general mutable access expands the range. Each type-check result gains an optional 16-byte range on this x86-64 target. The shared incremental format changes from 57124 to 65135, invalidating older format files. The experiment does not measure every caller of the modified node-type tables.

The two source states produced different generated files and program ELFs. Within each compiler, edited, settled, repaired and independently empty NEW yielded the same native reader and output. All four distinct original Linux executables were rerun. Their complete 153,626 canonical Unicode names round-tripped, all 481 aliases returned their published code points and all three negative lookups failed. The edit preserves the same 6,002,772-byte Unicode behavior stream. The deliberately out-of-range input failed twice on the real build path. The main packet contains the complete ELFs, native output, Cargo JSON messages, PMU records and selected compiler argv. [Registered source, expected generated bytes and reader](../../registration.json) · [Raw originals and GitHub SHA-256s](originals.json)

The local controls cover 36 seeded tables with 1,023, 1,024 and 1,025 elements, three integer widths and four literal forms. Both compilers produced the same typed HIR and six existing packed THIR arrays. Both rejected the out-of-range literal at bytes 152,344–152,347, twice. After repair the independent-empty executable matched the edited one within each compiler. The two retained edited executables reproduced their independently computed 36-value outputs. Eleven additional Cargo transitions switched compiler and integer width in both directions. Nine valid empty outputs were reopened and run. Two invalid histories gave the same overflow at bytes 2,102–2,105. The archive retains every numerical witness and the actual RSIC headers from the valid empty histories. [Local controls and physical disk inventories](local-controls.zip)

## Storage

Logical bytes and allocated bytes below cover each target and shared tree together, deduplicated by device and inode. The local edited Unicode check saved 3,260,303 logical bytes and 3,256,320 allocated bytes. The unrelated AST control added 9,324 logical bytes and 16,384 allocated bytes. These are local retained snapshots, separate from the hardware counters.

| Retained history | C5 logical / allocated | C6 logical / allocated | Unique files each |
|---|---:|---:|---:|
| Unicode check after edit | 73,123,506 / 74,825,728 | 69,863,203 / 71,569,408 | 723 |
| Unicode build after edit | 80,680,737 / 82,464,768 | 77,413,414 / 79,200,256 | 759 |
| Unrelated Ruff AST check | 91,663,559 / 92,807,168 | 91,672,883 / 92,823,552 | 407 |

## Offline verification

From this directory in a checkout of the QA evidence commit, on Linux x86-64 with Python 3.11 or later, run

```sh
python3 -IB verify.py --run-native --report /tmp/flat-hir-counts.json
cmp /tmp/flat-hir-counts.json counts.json
python3 -IB controls.py --run-native
```

The 6,449,712-byte lossless packet reconstructs the eight full original Actions ZIPs, which together contain 174,439,302 bytes. The reader verifies every retained span, reconstructed ZIP digest, CRC, source/transport registration, ordered arm and unique boot. Add `--extract-originals DIRECTORY` to retain the exact ZIP bytes, or `--gh-auto /path/to/gh-auto` to recheck Actions job and artifact identities while the artifacts remain available. The local package carries both factory qualification ZIPs and the installed driver identities. The full stage-1 SDKs remain in their original factory archives. Each source delta hunk uses full Git blob IDs and zero context. [Offline reader](verify.py) · [Local control receiver](controls.py) · [Packet builder](pack.py)
