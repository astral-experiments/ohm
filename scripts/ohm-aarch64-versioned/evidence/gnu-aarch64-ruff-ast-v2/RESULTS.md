# Held-out GNU AArch64 cross-build results

The twelve independent blocks compare the public #276 compiler (A), the GNU zmij-only prerequisite (N), and the complete GNU compiler (V). Every installation used the same Cargo reader built on #293. The command built Ruff’s AST rlib on x86-64 Linux for AArch64 GNU Linux after the original 74-file Python 3.15 edit.

| Rust comparison | Ordinary action | Prior instructions, median | V instructions, median | Median paired ratio | Simultaneous median interval | Observed range |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Public #276 / V | First edit | 41.252B | 8.301B | 4.969× | 4.968–4.971× | 4.968–4.972× |
| Public #276 / V | Edit + immediate repeat | 80.043B | 8.452B | 9.471× | 9.469–9.473× | 9.469–9.474× |
| Public #276 / V | Settled unchanged | 38.702B | 0.151B | 256.773× | 256.732–256.817× | 256.710–256.841× |
| GNU zmij prerequisite / V | First edit | 40.209B | 8.301B | 4.844× | 4.843–4.845× | 4.843–4.845× |
| GNU zmij prerequisite / V | Edit + immediate repeat | 77.961B | 8.452B | 9.224× | 9.222–9.226× | 9.222–9.227× |
| GNU zmij prerequisite / V | Settled unchanged | 37.661B | 0.151B | 249.857× | 249.826–249.885× | 249.803–249.899× |

Each comparison exceeded 2× in all twelve blocks. For each predeclared endpoint, the one-sided sign test against 2× gives p = 1/4,096. This is the paired sign test, distinct from a treatment-order randomization test. All six three-role orders occurred twice. The intervals are the second and eleventh ordered paired ratios. Their simultaneous family coverage is at least 96.19% across all six comparisons. The marginal instruction medians describe the two arms separately; the ratios use the matched block counts. The two pilot blocks and standalone reviewer supplied no observations.

The actual first-edit compiler roster was zmij, compact_str and ruff_python_ast on A, compact_str and ruff_python_ast on N, and ruff_python_ast on V. The repeats launched three, two and zero rustcs respectively. Counts include host Cargo and all threads of its actual compiler children. The command emits a Rust library. Cross-GCC, collect2, GNU ld and the QEMU consumer ran separately to verify the final native executable. The study measured guest instructions; it did not time a native AArch64 build or the linked application.

All 95 ordered Ruff AST object payloads and the edited consumer matched independently empty builds. The complete AArch64 consumer ran and returned the edited Python versions. The historical source and deliberately contrary consumer each produced their expected compiler error. Earlier unversioned native-library failures, the original worker-namespace rejection and the disjoint historical reader failure are retained in the registration and provider reports. The authentic signed -20 Cargo served as an old-reader safety control. Its #294 release source uses a different native-input policy and requires independent integration measurements.

[Original hosted acquisition and independent raw readback](https://github.com/astral-experiments/ohm/actions/runs/41091078814) · [Separate standalone reviewer](https://github.com/astral-experiments/ohm/actions/runs/41097294444)
