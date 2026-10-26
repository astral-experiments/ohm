# Six Cargo changes, two rustc changes and the ThinLTO Wild package

On Ruff `93526150df078af7dd8fc4226cdcc469539d2001`, the nine changes reduced the instructions used to rebuild an edited workspace binary by 2.49% and an edited formatter test executable by 1.81%. Each command used a clone of the same native dependency snapshot. A fixed wrapper selected the corresponding compiler driver for every invocation of the one dirty Ruff target. [Source edits and Wild package](README.md) · [Six Cargo changes](https://github.com/astral-sh/ohm-cargo/blob/5b76ff636a6c9c229a4629c43c88beb4cc6f50cc/benchmarks/ruff-dev-loop-20261026/cargo-stack/six.patch) · [First compiler change](https://github.com/astral-sh/ohm-rust/pull/230) · [Second compiler change](https://github.com/astral-sh/ohm-rust/pull/231)

| Warm Ruff workspace command | Parent median | Nine-change median | Paired whole-command instruction reduction (95% CI) |
| --- | ---: | ---: | ---: |
| `cargo +ohm build` | 5.519B | 5.382B | 2.488% (2.475–2.501%) |
| `cargo +ohm test --no-run` | 4.619B | 4.535B | 1.812% (1.691–1.932%) |

The build edited `"ruff failed"` to `"Ruff failed"` in `crates/ruff/src/main.rs`, then compiled only the Ruff CLI among 501 units. The test build changed the first letter of `"Unformatted code to be valid syntax"` in `crates/ruff_python_formatter/tests/fixtures.rs`, then compiled only `fixtures` among 619 units. Six pairs per command used each edit direction. All twelve pairs favored the nine changes in each command, with exact two-sided p = 0.000488. The first and last six build pairs gave 2.483% and 2.493%. The corresponding test-build halves gave 1.820% and 1.804%. Intervals use 40,000 block-bootstrap resamples stratified by edit direction. The test binaries never ran. [Predeclared input digests, seeds and orders](integrated-plan.json) · [Paired raw counts](integrated.csv) · [Analysis](analyze.py)

We first rebuilt dependencies separately under each compiler. The complete binaries differed because jemalloc embedded its compiler-specific Ohm artifact directory in debug data. For the changed Ruff CLI, this altered one entry in a multiset of 169,034 strings. Rust code, read-only data and line tables matched. Decoding `.debug_info` and `.debug_macro` produced the same 17,031,333 Ruff lines and 21,403,999 ty lines after replacing that one directory in the diagnostic text. This comparison failed the raw ELF equality gate and contributed zero observations. We kept all six distinct mismatching files with their SHA-256 digests. [Native differences](integrated-strict-native.json) · [Per-section digests](integrated-strict-sections.json) · [Decoded DWARF diagnostics](integrated-strict-debug.json) · [Retained files](integrated-strict-retention.json)

For the measured cohort, baseline dependencies were compiled once at the final absolute target and build paths. We physically separated the two arm directories and verified their complete manifests were equal before any edits. Warm build snapshots had 14,695 entries (6.02 GB of unique file content) and test snapshots had 24,408 entries (13.65 GB). Both arms retained the same rustc frontend, LLVM library and standard library. We checked the expected driver actually loaded in every counted rustc process. Every reset and scored command matched all six or 102 genuine native executable SHA-256 digests for that source state, as well as the entire native unit graph. [Independent native output digests](integrated-native.csv) · [Snapshots, executable identities and per-run receipts](integrated-audit.json)

The instrumented commands used Clang as the compiler driver and invoked Wild with `--no-fork`. The native `execve` traces showed four application processes after accounting for transparent `exec` wrappers. DynamoRIO counted Cargo in-process with child following disabled. Its complete thread-start, thread-final and process-final records matched. A separate Cachegrind instance covered the one dirty rustc and its Clang and Wild descendants in the *same command*. Each of those three profiles had a single matching terminal instruction total. Enclosing Cargo in Cachegrind changed the native dependency namespace. A DynamoRIO-only attempt with child following did not provide complete fork/exec counts. We excluded those attempts. [Mixed collector and native roster checks](mixed-holdout.py) · [Individual process counters](integrated.csv)

On the exact same single-threaded released Wild replay, Cachegrind recorded 3.336–3.338B instructions and DynamoRIO recorded 3.247–3.248B. The median DynamoRIO level was 2.69% lower on that link. Each replay produced the same 159,500,664-byte native ELF. The integrated table uses a fixed collector for each of the four process roles in both arms. The calibration measures this specific link and supplies no conversion factor for Cargo. [Paired collector calibration](integrated-calibration.json) · [Calibration runner](calibrate-counters.py)

| Component | Parent SHA-256 | Nine-change SHA-256 |
| --- | --- | --- |
| Cargo | `211465de4b9e4589da2be06871acd9304dd3b94c849c1304f723484cb4f71dfc` | `71da9dfcb3ba440297f84705ff7e3a676634ced7d7b6ca9b525a439b7f748f58` |
| rustc driver | `58a8a5b3bd9364659d7d1e5aaff46ca44286fad2580f8dcf3e348ad4b6cdfa11` | `244cf510684e96c444fae9be8b91f7a9b11b83388a5c843f5e310adf3c2f3962` |
| Wild | `0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5` | `076b2067722a82b6445183fcabc26a17819537e1656067ec85947b5800ba2a23` |

Cargo started at `461a3d1007ecc997a6d86c7d75e8b518575c8d90`. The six-change patch has SHA-256 `1936359d4dd3071813406cf97bf291fb559d624efb0f80f74e0254545e5a6681`. Changes five and six are `fc82ecb6f31cea7da5dba628e697fe80ed05acd9` and `f9b4bba66b74fa2be213901ff6ec12c468530b1b`. The compiler started at `f1a7cf9d20b2cae39e991b178b56ba06b43dc8fa`, then added `35d8a96ee65b02f3093c00eb517cba98f791f60e` and `1a34d106ed0e73e8a9074ffd36a6963de86b6a27`. [First four Cargo drafts](combined.md) · [Cargo #246](https://github.com/astral-sh/ohm-cargo/pull/246) · [Cargo #247](https://github.com/astral-sh/ohm-cargo/pull/247) · [Compiler release recipe and training inputs](https://github.com/astral-sh/ohm-cargo/tree/eefad11f1290e06d6227c8509e3be3b792b99506/benchmarks/ruff-dev-loop-20261026/packed-edges) · [Packaged Wild](https://github.com/astral-sh/ohm/pull/185)

## Reproduction

Use a hydrated Cargo registry, two disposable Ruff checkouts at the revision above, the pinned binaries and a DynamoRIO 11.91.20741 Linux x86-64 SDK. The client was rebuilt twice with SHA-256 `79f0c15d45b8d6b58a657b1816d4c2db2f798a9dbba4a1d02b3f2f3a1bda8204`. The source below has SHA-256 `507b7a51d497c389a2d15829cb6de639718289e7c4b2c7e2a76d7652c30f8174`. Valgrind was 3.22.0. Use the supplied native source to build the client, then assign `DR_CLIENT` to its shared library. [DynamoRIO counter](counter/counter.c) · [CMake project](counter/CMakeLists.txt) · [Assembly qualification fixture](counter/toy.S)

```sh
cmake -S counter -B counter-build -DDynamoRIO_DIR="$DR_SDK/cmake" -DCMAKE_BUILD_TYPE=Release
cmake --build counter-build -j 2
cc -nostdlib -static -Wl,--build-id=none counter/toy.S -o counter-build/toy
DR_CLIENT="$PWD/counter-build/libpidcounter.so"
python3 make-final-inputs.py --help
```

Pass local component and registry paths to `make-final-inputs.py` and write its result to `$INPUTS`. Use the exact pristine driver digest in the table above. The bootstrap reproduces the successful native snapshot and mixed-collector recipe directly. It checks the untouched native workspace, copies and verifies the warm state, then asserts the native/guest oracles and process identities in both arms. It also checks a 24-GiB free-space reserve. The initial failed instrumented warmups from the investigation are unnecessary for reproduction. Substitute a separate empty state directory, output directory and Ruff checkout for each command. [Input manifest](make-final-inputs.py) · [Native oracle and snapshot protocol](final-holdout.py) · [Strict full-toolchain comparison](full-toolchain-preflight.py) · [Bootstrap and replay](reproduce-integrated.py)

```sh
for action in bootstrap measure; do
  python3 reproduce-integrated.py "$action" build "$RUFF_BUILD" "$INPUTS" "$STATES/build" "$OUT/build" \
    --drrun "$DR_SDK/bin64/drrun" --pidcounter "$DR_CLIENT"
  python3 reproduce-integrated.py "$action" test "$RUFF_TEST" "$INPUTS" "$STATES/test" "$OUT/test" \
    --drrun "$DR_SDK/bin64/drrun" --pidcounter "$DR_CLIENT"
done
python3 final-results.py integrated-plan.json "$OUT/build" "$OUT/test" "$OUT/export" analyze.py
python3 analyze.py integrated.csv parent stack
```
