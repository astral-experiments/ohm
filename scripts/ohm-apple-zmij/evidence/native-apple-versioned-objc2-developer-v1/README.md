# Versioned Darwin native-link advisories on the ordinary ty developer build

The two native Apple Rust subjects were 9b4b11ce8cb84020be10dc54a6426807bfa87caa and d97de79d0462fec6b08474c677857b6b058f56c2 on one Cargo 9a102b4519b40f9034aa40533d92c83583dcb289. The compiler build used the same stage0 binary, sources outside the registered Rust delta, target standard libraries, host frontend and Xcode. The only changed SDK file was the Rust driver. Both emit the same versioned advisory. Their relink-input classification differs only in the ObjC frame-pointer instruction under study. The compiler images were source-built on macOS without distribution PGO. [Original registered native run](https://github.com/astral-experiments/ohm/actions/runs/41091420073)

The historical Ruff #28877 checkout changed the behavior of literal response files. Each independent empty installation received `cargo +ohm build -p ty --bin ty --locked --offline -j4 --message-format=json`, the original edit, and two unchanged builds. Compilers ran with the local positive-list environment, observed `-C incremental`, settled graphs and real object files. All foreground work including Cargo, residual compiler checks and any linker processes is included. The ordinary timed commands were unwrapped.

| Foreground command | Parent median seconds | Child median seconds | Median paired ratio | 96.14% interval | One-sided p at 2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| Historical edit | 1.9160 | 1.5309 | 1.2567× | 1.2196–1.3231 | 1.00000 |
| First unchanged | 0.7142 | 0.3239 | 2.2199× | 2.1112–2.3507 | 0.00108 |
| Further unchanged | 0.7124 | 0.3232 | 2.2009× | 2.1325–2.3899 | 0.00108 |
| Edit plus first unchanged | 2.6393 | 1.8491 | 1.4332× | 1.3809–1.5125 | 1.00000 |

The first unchanged endpoint passed its registered twofold gate. 12/12 individual intervals exceeded twofold. The interval uses the third and tenth paired order statistics. The hypothesis test enumerates the 924 six/six allocations. Two separate pilot pairs had ratios 2.1262× and 2.3159×. Median process-tree CPU on the primary was 1.715 s and 0.815 s. Darwin's retired instructions were unavailable or inconclusive. Median private Cargo allocated footprint was 2606.0 MiB and 2606.2 MiB.

Native preflight counts below are full rustc / link-only rustc / all Xcode links / final ty links / full objc2 compilers. Each field separately gives the PC and CP orders. Every timed invocation was checked against its structural counterpart and the independently empty native target at the same state.

| Role | Edit | First unchanged | Further unchanged |
| --- | --- | --- | --- |
| P | 4/0/1/1/1, 4/0/1/1/1 | 1/1/1/1/1, 1/1/1/1/1 | 1/1/1/1/1, 1/1/1/1/1 |
| C | 3/0/1/1/0, 3/0/1/1/0 | 0/1/1/1/0, 0/1/1/1/0 | 0/1/1/1/0, 0/1/1/1/0 |

The original ty executable, its changed response-file outputs and two real diagnostics, E0425/101 and the repaired binary were checked. Native recipe/stock linker operands and the underlying complete physical CGUs were reopened. All code/data, original code signatures and native linker paths are retained. The only admitted same-role image variation is the authenticated temporary CGU nonce in N_OSO and corresponding ad-hoc signature hashes. An across-role canonicalization separately admits the proven Cargo workspace component for an actual linking operand. Raw binaries are recoverable from per-archive digests and 256 KiB chunks.

The native matrix independently ran 1,176 direct/library, watched/unwatched, same-stamp, malformed, removal, Rust edit and repair commands on the signed, classic and aware receivers. All required verdicts matched independently empty physical references. Additional controls exercised 72 same-target legacy→aware→legacy transitions, 36 genuine tracked marker-name conflicts and 12 real published-registry commands. On the unchanged real zmij/zlib-rs caller the signed and classic receivers ran three full compilers and Xcode once. Aware Cargo ran one link-only rustc and zero full rustcs or Xcode links. The explicit defaults-off, unwatched stale results are preserved. [Native safety details](native-compatibility.md)

The original unversioned ObjC/signed −20 pair exhibited ten adverse default results. Its separate #293 performance studies, the unversioned signed controls and CI-mode builds contribute zero pairs to this cohort. [Unversioned signed safety control](https://github.com/astral-experiments/ohm/actions/runs/41085838553) · [Original Cargo #293 diagnostic](https://github.com/astral-experiments/ohm/tree/d591f0f283b90482c92a033f795b16e3ba2b9c1e/scripts/ohm-apple-zmij/evidence/native-apple-objc2-cargo293-developer-diagnostic-v1)

The Rust draft stacks the two measured product commits onto the current #277 branch. Git tree comparison found only the inherited `.github/workflows/ci.yml` differs from the measured child. The compiler, standard library, tests, bootstrap and all other files agree. [Source mapping](published-source.json)

Use `python3 -IB verify.py` for the offline portable check. To replay the four archived Actions artifacts, install the BLAKE3 command-line utility and run `python3 -IB reopen-raw.py /path/to/apple-versioned-provider-and-migration.zip /path/to/apple-versioned-local-ty-traced.zip /path/to/apple-versioned-local-ty-pilots.zip /path/to/apple-versioned-local-ty-final.zip` from this directory. The separate small `terminal_clocks.py` reader recomputes the paired results directly from original process starts and stops.
