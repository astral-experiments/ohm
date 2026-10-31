# Source-built Rust on Ruff check and build

**The registered two-command study failed its native build gate.** Each worker measured all six check configurations. Both encountered an extra full compiler process on the linked build. The O1 build and native-provider panels never ran. The table below describes the completed checks and can be used to reject a 2× check claim. The study has zero qualifying whole-panel comparisons. [Original registration](../PLAN.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41160280371)

Both workers used Cargo `761ea115` and signed -21 Wild. P is the complete enrolled source-built Rust `c79998a5` kit. C uses the same source bootstrap settings and candidate Rust tree `0d30133a`. Each kit includes its own 68 enrolled files and its own compiler driver. These are compact QA SDKs. The absolute executable path, settings, source and Cargo CLI matched within each P/C comparison. The selected library's own checkout and user data were isolated. The positive and invalid edits come from the original pinned Ruff checkout at `93526150`. [Compiler construction and admission](https://github.com/astral-experiments/ohm/actions/runs/41157899149)

| Same-profile P instructions / C instructions | Worker 01 | Worker 02 |
| --- | ---: | ---: |
| Default check, first unchanged | 1.0006× | 1.0000× |
| O1 check, empty | 1.0029× | 1.0030× |
| O1 check, neutral unchanged | 1.2142× | 1.2111× |
| O1 check, real edit | 1.1442× | 1.1429× |
| O1 check, first unchanged | 1.1926× | 1.1918× |
| O1 check, edit plus first unchanged | 1.1650× | 1.1639× |
| O2 check, first unchanged | 0.9974× | 0.9974× |

O1 and O2 select only the generator package's supported private profile override. On Worker 01 O1's first unchanged check took 12.948 billion native user instructions with P and 10.857 billion with C. On Worker 02 the corresponding counts were 12.933 and 10.851 billion. Retained fresh target plus shared storage at O1 fell by 0.246 and 0.270 MiB, near 806 MiB on each. The C installed SDK occupied 81,920 additional bytes. This trial used separate empty roots and cannot estimate space during an upgrade. [Raw check counts, allocations and per-phase physical evidence](incomplete.json)

The regular command was `cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json`. All 120 native check visits, 56 whole-tree instruction calibrations, 12 real-library-edit errors and their 12 independent empty equivalents passed the check subpanel. At each active profile the independent empty trace contained 304 full compiler invocations and 48 Wild links. Its unchanged trace contained three full compilers and one Wild link. The three Cargo-launched compiler PIDs in each independent driver observation loaded the physical driver corresponding to the enrolled Rust source. Both repaired and healthy commands emitted the same 303-artifact logical inventory on a 338-unit graph. The checked three generated files and O1 package settings matched. Neither reported O1 check endpoint reached the preregistered 1.80× threshold.

The ordinary linked command was `cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json`. The P/C O0 builds finished on Worker 01 and the P/C O2 builds finished on Worker 02. All four matched their own empty four-codepoint reader and generated files, including after the historical generator edit. The returned executable bytes also match across compilers within each worker. Whole target rlib digests changed on each warm compile and differ from independent empty artifacts. The original signed study also saw different empty rlib digests and matched reader bytes. This packet retains target rlib digest attestations and the returned reader ELF bodies.

The declared dirty units were build-script-build and unicode_names2 both here and under signed -21. At both available source-built levels rustc physically ran for each, then Wild linked only the host build script. At O0 the compiler PIDs were 111420/111455 on P and 113141/113176 on C. At O2 they were 112812/112854 and 111277/111319. The true signed O0 and O1 comparison skipped the consumer's physical rustc and retained its warm rlib. [Signed comparison](https://github.com/astral-experiments/ohm/tree/e2dffc67a5a3eeab53b8e1fcded93f7896dc325c/scripts/strict-one-package/result) · [Namespace markers, syscall-bound settings, and signed controls](trust.json)

The 30-byte `.ohm-worktree-seed-deny-v7` file was present from the cold build on all four source-built linked histories and absent in the matching previous signed runs. Cargo refuses after-script reuse when that marker exists. The compact kits omit `bin/rustdoc`. The actual Ruff build-script process inherited `RUSTDOC=rustdoc` from Cargo, and each compiler reported a physical sysroot ending in `ordinary-ron-check/sdk-21`. That combination cannot satisfy either missing-rustdoc exception. The selected path is relative, and Cargo requires a physical sysroot with a `toolchains` parent before it will authenticate a fallback rustup proxy. This establishes one failing input to Cargo's trust predicate. The goal of the custody test and the physical driver check was met, but these installations do not reproduce the signed build's workspace reuse. [Trust checks](https://github.com/astral-experiments/ohm-cargo/blob/761ea115605c34f11a1cd29afd68812c1e1359dd/src/compiler/build_runner/compilation_files.rs#L2234-L2280) · [After-script reuse](https://github.com/astral-experiments/ohm-cargo/blob/761ea115605c34f11a1cd29afd68812c1e1359dd/src/compiler/fingerprint/worktree.rs#L163-L185)

The two original GitHub ZIPs are unmodified. `actual-compiler-loop-01.zip` is 17,590,778 bytes, SHA-256 `dc64cbcd351bf84354d8ba16214d0694dfa199107cf811c0230a51de7b14ed9b`. `actual-compiler-loop-02.zip` is 17,465,365 bytes, SHA-256 `47014ca5faab4418128ee60dd54d56addf0e30293548a70e387d86c5f65c5317`. The first two revisions stopped in QA-only receipt code before a pair completed. [Distinct raw custody and exclusions for both earlier failures](qa-setup-stops.json)

Run from a checkout containing this packet. The first command reopens the failed study without a compiler, Cargo, or network access. The second accepts a second checkout of the immutable signed comparison, including its original ZIPs.

```sh
python3 -IB scripts/native-compiler-loop/result/incomplete.py --out /tmp/actual-compiler-incomplete.json
python3 -IB scripts/native-compiler-loop/result/trust.py /path/to/signed/scripts/strict-one-package/result --out /tmp/actual-compiler-trust.json
cmp scripts/native-compiler-loop/result/incomplete.json /tmp/actual-compiler-incomplete.json
cmp scripts/native-compiler-loop/result/trust.json /tmp/actual-compiler-trust.json
```
