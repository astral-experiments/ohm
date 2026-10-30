# Native Apple Ruff test-build verification

The command is `cargo +ohm test --lib --no-run -p ruff_python_ast --locked --offline -j4 --message-format=json` on Apple silicon. The primary observation is the first unchanged command after applying Ruff #28335 to a settled checkout on one branch. The edit and second unchanged command have separate rows. [Native run 41056802208](https://github.com/astral-experiments/ohm/actions/runs/41056802208) · [registered harness](https://github.com/astral-experiments/ohm/tree/51f61408905b3f1abe913641b5c13a1346011d77/scripts/ohm-apple-zmij) · [compiler change](https://github.com/astral-experiments/ohm-rust/pull/276)

| Cohort | Command | P median ms | C median ms | Median paired P/C | Median ratio interval |
|---|---|---:|---:|---:|---:|
| screen, n=2 | edit | 1531.12 | 1488.85 | 1.030× | — |
| screen, n=2 | repeat-1 | 1506.57 | 38.39 | 39.239× | — |
| screen, n=2 | repeat-2 | 1512.63 | 38.08 | 39.709× | — |
| confirm, n=12 | edit | 1486.46 | 1382.33 | 1.080× | 1.031–1.103 |
| confirm, n=12 | repeat-1 | 1562.73 | 39.49 | 39.059× | 37.308–39.906 |
| confirm, n=12 | repeat-2 | 1466.08 | 37.15 | 38.861× | 36.923–40.698 |

P is Rust #275 (`2035696c5316079f5b2e4373aee834839aac97e9`). C is its direct child (`444c0273a2e2bc0b161e988d43c882349bc2d7a6`). Both use signed -20 Cargo `2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c`. They share 2,465 of 2,466 runtime file contents and the same source stamp and bootstrap command. The matched stage-1 compiler driver differs. The package uses Xcode's stock linker. The benchmark has one Apple host and toolchain configuration.

The separate 12-pair confirmation passed the registered primary gate. The median interval uses the third and tenth ordered ratios (96.1426% coverage for n=12). The one-sided sharp 2× randomization test gives p=0.001082 across all 924 balanced allocations. Each pair has two independently installed private Cargo, target and build directories. The second repetition is a secondary endpoint from the same installations.

Adding the edit and the first repeat within each confirmation pair gives medians of 3.044 s for P and 1.421 s for C, with a median paired ratio of 2.082×. All 12 ratios exceeded 2×. This is an exploratory calculation. The equivalent two pilot ratios were 1.897× and 2.084×. To reproduce it, add the `edit` and `repeat-1` values by arm and pair in the verifier’s `estimates_ns` output.

After the historical source edit, kernel exec observation recorded `ruff_python_ast`, `zmij` and 1 stock linker call for P and `ruff_python_ast` and 1 stock linker call for C.
On the first unchanged command, kernel exec observation recorded `ruff_python_ast`, `zmij` and 1 stock linker call for P and zero rustc processes and 0 stock linker calls for C.
On the second unchanged command, kernel exec observation recorded `ruff_python_ast`, `zmij` and 1 stock linker call for P and zero rustc processes and 0 stock linker calls for C.

The archive contains 84 untraced foreground edit/repetition clocks, 28 independent timed installations, and 56 post-clock, independently empty builds matching their installation's driver path, inode, device and nanosecond ctime. Each timed old/new executable equals its own empty build in every raw byte. The 220 successful harness invocations supplied 11,808 named successful test outcomes, with no ignored tests. The history has 53 tests before the edit and 54 after. The new test is `nodes::tests::f_string_parts`. In each cohort both compilers reject the same invalid edit with E0425. After repair, the executable matches the independently clean file.

Different compiler installations legitimately receive different Cargo target paths. The verifier authenticates every original CodeDirectory page, binds the N_OSO debug-symbol paths to the actual kernel-observed linker’s exact operands, and permits changing only the 16-hex v2 installation namespace in those paths. It then recomputes those signature page hashes and compares the entire byte string. This covers 29 old or 30 new N_OSO values, including 14 archive members. The portable table preserves every original raw image digest and the full equality result, along with native section and test inventory data. The upstream artifact retains every distinct complete test Mach-O.

The independent C archive control exercises 17, unchanged 17, replacement 29, malformed archive (Cargo 101), missing archive (Cargo 101), repaired 29 and a clean 29. Linker exec records, program values and executable SHA receipts bind the successful native calls. The repaired and independently clean executables match. This small provider fixture retains the value and Mach-O digest for each successful call. The full Ruff test Mach-O files themselves are archived separately.

The clock calibration compared zero iterations with 200 million iterations of a two-instruction loop at the parent, child and grandchild levels. Whole-process-tree CPU calibration passed. Darwin retired-instruction scope was `unavailable-or-inconclusive`. Native process counts come from separate Endpoint Security flanks. All measured Cargo invocations ran in the foreground without that observer.

The signed -20 pilot found no physical rustc or linker on either unchanged `cargo check` command for this target. This qualified comparison consequently measures the test build. Three earlier native acquisitions did not meet their own output gates and contributed zero completed timing pairs. `excluded.json` reports each original evidence ZIP and, for the third attempt, the regenerated hash of each unpaired parent output.

## Offline verification

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
python3 -IB verify.py --raw /path/to/apple-zmij-qualified-verbs.zip
# Optional, for the signed preliminary pilot
python3 -IB signed.py /path/to/apple-zmij-signed-verbs.zip
# Optional, for one of the three failed raw archives
python3 -IB previous.py /path/to/excluded-archive.zip
```

The untouched qualified Actions ZIP has 2,768 members and SHA-256 `508d39349494372031d4dab404deb0ae530c7f6eb2e5578151c8f269a325ee99`. Artifact ID is 12978348672. The portable verification recomputes the paired estimates, typed and physical work, every semantic control and the registered promotion rule from the projection. Supplying the raw ZIP additionally recomputes the projection from all original timing, native, Cargo, complete test and Mach-O streams. The retained calibration and test programs are read as data and no compiler or GitHub access is required to verify.
