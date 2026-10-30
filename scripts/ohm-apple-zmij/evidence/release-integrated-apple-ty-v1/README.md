# Native Apple developer builds on the shipped Cargo lineage

Ruff’s real response-file edit changes the two invocations of the resulting `ty` executable. Its old executable reports success. Its new executable returns 1 with two diagnostics for `@list.py` and `@package/main.py`. Each arm also rejects an invalid Rust edit with E0425 and Cargo 101, then produces the independent clean program after repair. The ordinary command was `cargo +ohm build -p ty --bin ty --locked --offline -j4 --message-format=json`. The two Rust revisions and two Cargo products below are different comparisons. [Original registration](registration.md) · [Ruff edit](https://github.com/astral-sh/ruff/commit/915bb2b4bf9ae7eee47cf55646bbfebae254a23b) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41114554812)

The enrolled native host used Mac OS 15.7.5 on arm64, APFS, and Xcode 16.0 (build 16A242d). The observer physically calibrated stock Apple ld `2b48a59af702` against a linked Mach-O and its exit status. [Source, SDK, Cargo and observer records](native-subjects.json.gz)

## Compiler change on the integrated Cargo

The versioned CRC compiler `9b4b11ce` is compared with [Rust #281](https://github.com/astral-experiments/ohm-rust/pull/281) at `01dccb63`. Both use the same integrated Cargo Mach-O, source `fd55a13d`, SHA-256 `9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d`. Of 2,466 SDK members, only the compiler driver changed. Both used the same stage-zero inputs and 54 enrolled standard-library directory entries. [Integrated Cargo source](https://github.com/astral-experiments/ohm-cargo/commit/fd55a13d0220748794ba3c7c9556ef8ceed8591f)

The first two columns below give the full rustc / link-only rustc / all Xcode links / final ty links / full objc2 compiles from each role. Both compiler orders have a separate physical trace.

| Physical command | Parent or signed (PC, CP) | Child or integrated (PC, CP) |
| --- | --- | --- |
| cold | 357/0/57/1/1, 357/0/57/1/1 | 357/0/57/1/1, 357/0/57/1/1 |
| edit | 4/0/1/1/1, 4/0/1/1/1 | 3/0/1/1/0, 3/0/1/1/0 |
| repeat-1 | 1/1/1/1/1, 1/1/1/1/1 | 0/1/1/1/0, 0/1/1/1/0 |
| repeat-2 | 1/1/1/1/1, 1/1/1/1/1 | 0/1/1/1/0, 0/1/1/1/0 |
| invalid | 2/0/0/0/1, 2/0/0/0/1 | 1/0/0/0/0, 1/0/0/0/0 |
| repair | 3/0/1/1/1, 3/0/1/1/1 | 2/0/1/1/0, 2/0/1/1/0 |

The two mirrored pilot ratios on the first unchanged invocation were 2.2724× and 2.1495×. Both exceeded 2×. [Original archive](https://github.com/astral-experiments/ohm/actions/runs/41114554812/artifacts/13009355383)

The 12 new pairs **did not pass** the prespecified 2× inference on the first unchanged build. 7/12 ratios exceeded 2×. The two pilot pairs contribute zero additional observations to this comparison. [Original archive](https://github.com/astral-experiments/ohm/actions/runs/41114554812/artifacts/13010718689)

| Phase | Parent or signed, s | Child or integrated, s | Paired median | 96.14% interval | One-sided p at 2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| edit | 2.2216 | 1.8175 | 1.2162× | 1.1132–1.2654 | 1.00000 |
| repeat-1 | 0.7608 | 0.3824 | 2.0141× | 1.9400–2.2007 | 0.11147 |
| repeat-2 | 0.7671 | 0.3888 | 2.0246× | 1.8662–2.3305 | 0.20671 |
| edit+repeat-1 | 3.0063 | 2.2009 | 1.3669× | 1.2696–1.3977 | 1.00000 |

Median calibrated user plus system CPU for the primary was 1.805 s and 0.950 s. Median allocated Cargo footprint was 2608.9 MiB and 2607.9 MiB. The CPU calibration classified Darwin retired instructions as `unavailable-or-inconclusive`.

## Cargo change on the published compiler

Both arms use the same source-built #281 compiler, standard library and Xcode linker. The baseline Cargo is the authenticated signed -20 distribution at `2d44bd4a`. The integrated Cargo is the all-static, Ohm-defaults optimized build at `fd55a13d` on that signed toolchain. The signed product includes its shipping optimization profile, while the source-built integrated binary did not receive distribution PGO. This is a comparison of the actual two products. [Signed release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-20) · [Two-parent integration](https://github.com/astral-experiments/ohm-cargo/commit/fd55a13d0220748794ba3c7c9556ef8ceed8591f)

The first two columns below give the full rustc / link-only rustc / all Xcode links / final ty links / full objc2 compiles from each role. Both compiler orders have a separate physical trace.

| Physical command | Parent or signed (PC, CP) | Child or integrated (PC, CP) |
| --- | --- | --- |
| cold | 357/0/57/1/1, 357/0/57/1/1 | 357/0/57/1/1, 357/0/57/1/1 |
| edit | 10/0/1/1/1, 10/0/1/1/1 | 3/0/1/1/0, 3/0/1/1/0 |
| repeat-1 | 8/0/1/1/1, 8/0/1/1/1 | 0/1/1/1/0, 0/1/1/1/0 |
| repeat-2 | 8/0/1/1/1, 8/0/1/1/1 | 0/1/1/1/0, 0/1/1/1/0 |
| invalid | 8/0/0/0/1, 8/0/0/0/1 | 1/0/0/0/0, 1/0/0/0/0 |
| repair | 9/0/1/1/1, 9/0/1/1/1 | 2/0/1/1/0, 2/0/1/1/0 |

The eight full rustc processes under signed Cargo built `compact_str`, `objc2`, `ruff_python_ast`, `ty`, `ty_ide`, `ty_module_resolver`, `ty_python_semantic`, `zmij`. With the integrated reader, the only compiler invocation on each repeat was the link-only `ty` unit, and Xcode still linked the final binary. The source-level compiler-only comparison above isolates #281 from these other Cargo effects.

The two mirrored pilot ratios on the first unchanged invocation were 16.6368× and 18.5201×. Both exceeded 2×. [Original archive](https://github.com/astral-experiments/ohm/actions/runs/41114554812/artifacts/13012803774)

The 12 new pairs passed the prespecified 2× inference on the first unchanged build. 12/12 ratios exceeded 2×. The two pilot pairs contribute zero additional observations to this comparison. [Original archive](https://github.com/astral-experiments/ohm/actions/runs/41114554812/artifacts/13016403124)

| Phase | Parent or signed, s | Child or integrated, s | Paired median | 96.14% interval | One-sided p at 2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| edit | 7.7507 | 1.9156 | 4.0065× | 3.9422–4.2086 | 0.00108 |
| repeat-1 | 6.2057 | 0.3898 | 15.9468× | 14.9283–16.7140 | 0.00108 |
| repeat-2 | 6.9826 | 0.3937 | 17.9000× | 16.6653–19.8860 | 0.00108 |
| edit+repeat-1 | 14.0718 | 2.3049 | 6.0405× | 5.7805–6.3607 | 0.00108 |

Median calibrated user plus system CPU for the primary was 8.050 s and 0.960 s. Median allocated Cargo footprint was 2506.4 MiB and 2607.5 MiB. The CPU calibration classified Darwin retired instructions as `unavailable-or-inconclusive`.

## Evidence and limitations

Each of the two warmup orders uses fresh working stores, independently empty old and edited builds, actual EndpointSecurity native exec events, the emitted and reread Cargo JSON, genuine per-crate incremental work products, and complete Mach-O executables bound to the physical root linker operands. The wire images are original Mach-O binaries. The comparison verifies code, data, code-signature page hashes and actual linker input objects. Authorized normalization is confined to the rooted temporary CGU nonce or Cargo workspace component in a physically established debug path and its signature hashes. All other bytes must agree. See the native readback for the role-specific and cross-role identities. Timed commands use no exec hook. Each measured program and recorded `.rlink` recipe is reread and compared to its independent native reference.

On both actual Apple hosts, the old signed v1 compiler and an unwatched native provider gave the same six stale warm results out of 44 visits under signed and integrated Cargo. In both direct and library placements, a higher-priority provider left 17 when clean returned 29. Malformed or missing provider bytes left a successful executable when clean returned Cargo 101. Strict #293 detected all six. Every declared input and real Rust edit agreed with empty. The separate 72 actual versioned Cargo upgrade and downgrade commands all matched their independent references. Signed, strict and merged Cargo each also passed the required 392-command default/declared matrix for the new protocol. The two host readbacks include actual kernel execs, provider archive bytes and complete programs. [Portable original provider matrix](providers/README.md) · [Apple Unicode and Linux release compatibility](https://github.com/astral-experiments/ohm/tree/7680d2e9a617878d953977f1ebc8be3363671abb/scripts/ohm-gnu-syscall/evidence/release-reader-compatibility) · [Linux exact Apple selector checks](https://github.com/astral-experiments/ohm/tree/0e959375a2eee415d615dd907a6c159320a0acfe/scripts/ohm-cargo-301-linux-ci/selector-delta)

The initial Apple workflow closed its provider controls and stopped on a QA import error before building ty. All 1,596 native provider outcomes and physical work counts repeated on the corrected host. For the 84 stand-alone literal and registry controls, the physical Xcode output path hashes changed with the host namespace. The path digest and the actual program output are separately recorded. The earlier attempt contributed zero timings. [Initial run](https://github.com/astral-experiments/ohm/actions/runs/41110754345)

Run `python3 -IB verify.py` with Python 3.11 or later to recheck the compact paired measurements and original native counts entirely offline. For a full native reproduction, download the final cumulative ZIP in `index.json` and run `python3 -IB reopen.py ARCHIVE.zip`. The SHA-256 manifest commits the full projection. The small `terminal_clocks.py` reader can separately derive the numbers without using the workflow’s summary. `python3 -IB providers/verify.py` verifies the independent first provider attempt including its adverse cases.

The terminal archive contains 18,955 original files. The independent per-path SHA-256 manifest is `a002ec3f70c7f6a03319704dce148ad0568e326f9f3ce58c1bce1b779a00b246`. On all six uploads, the only changed earlier member was the active Cargo selector pointer when switching back to signed. The original member hashes remain in the acquisition receipts.

```sh
gh-auto api --allow-escape-sequences repos/astral-experiments/ohm/actions/artifacts/13016403124/zip > apple-final.zip
python3 -IB reopen.py apple-final.zip
python3 -IB terminal_clocks.py apple-final.zip rust confirmation rust-clocks.json
python3 -IB terminal_clocks.py apple-final.zip cargo confirmation cargo-clocks.json
```
