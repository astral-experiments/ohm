# Compatibility performance evidence

This archive contains the complete separate 90-command Linux confirmation, its immediate compiler/Cargo/native admission receipts, frozen controls, original edited source files, and two independent calculations. It needs no earlier benchmark archive. The final published Cargo follow-up is in the adjacent correctness evidence; timings used frozen Cargo 20b, not its later binary.

From this published directory, using Python 3.12 or newer:

```sh
python3 verify-performance-archive.py compatibility-performance.tar.gz package.json reproduced-proof
python3 reproduced-proof/compatibility-proof/harness/summarize_compatibility.py reproduced-proof/compatibility-proof --source-snapshots reproduced-proof/compatibility-proof/fixtures/source-originals --output reproduced-results
python3 reproduced-proof/compatibility-proof/harness/audit_pair_math.py --samples reproduced-results/samples.jsonl --summary reproduced-results/summary.json --output reproduced-pair-math.json
cmp summary.json reproduced-results/summary.json
cmp validation.json reproduced-results/validation.json
cmp independent-pair-math.json reproduced-pair-math.json
```

The first command verifies the compressed bytes against `package.json`, extracts regular files into a new directory without overwriting anything, and checks every payload path, size and SHA-256 against the archived inventory. The next commands verify raw timing/resource/source/runtime/cleanup receipts and independently recalculate the paired results. They do not build or run project binaries. Keep the output directories absent before starting. Extract the separate correctness archive into a different fresh directory; the two archives must not be overlaid.

There are two fresh rounds per comparison, with three sequential edits in each edit class. Those edits are not six independent rounds. Ruff's default arm stays in the middle position. The custom-Wild arm measures the whole explicit-linker configuration and cache-admission path, not only decoder time. Storage is settled allocated/logical bytes across the complete target/build lane; RSS is not PSS or peak disk. The binaries were not PGO/BOLT optimized, and this was not a cold-OS-cache experiment.

`results.md` is the readable extraction; `summary.json` retains absolute and percentage paired distributions and per-round values. All 90 raw rows and their logs remain under `compatibility-proof/evidence/performance-v1/`. Historic failed compiler/Cargo setup and validation receipts remain in the full raw collection; none are timing exclusions or accepted observations. The archive also includes the frozen parent harness files under `harness/origins/` for source inspection. Re-running the benchmarks themselves requires reconstructing the recorded devbox paths and toolchains; the commands above reproduce the evidence audit and calculations.
