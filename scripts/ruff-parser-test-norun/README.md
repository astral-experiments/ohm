# Ruff parser test-build instructions

This secondary Rust #353 study uses Ruff #29261, which changes both the Unicode data generator and its locked RNG dependencies. The primary outcome is the full `cargo +ohm test -p ruff_python_parser --lib --no-run --locked --offline` OLD-to-NEW command. Linux's inherited user-instruction counter covers Cargo, rustc, the linkers and their children. Cargo emits JSON messages. Listing and running the genuine parser test happen after the counter stops.

Each block uses an independent machine boot and both fully authenticated stage1 SDKs. The historical Rust sources are `f5a51d8c` and `6c2874a0`, with common released Ohm Cargo `abc70d60`. The original receiver, hardware calibration, 502 archives and Ruff transition come from packaging `2730f118`. Every role runs a cold OLD, real edit, settled NEW, the overflow twice, repair and an independently empty NEW. A copy of that role's OLD state supports one separate physical compiler/linker census. Each successful physical ELF is stored by full SHA-256. The verifier executes the retained ELF, checks all 246 names and runs one exact lexer test. Each role's edited, settled, repaired and independent empty ELF must match byte for byte. The table generator and physical artifact roster must match the prior two unpriced rehearsals.

Both independently booted pilot edits must save at least 5% before six fresh confirmations can begin. Confirmation needs six improvements and median savings of at least 5%. The two-sided exact paired sign test for six favorable signs gives 0.03125. The original consistent common-cost veto applies to cold OLD, cold NEW and settled NEW. Their absolute totals are reported. The [registration](registration.json) defines the complete decision.

Run the registered pilot from this QA checkout with an authenticated `gh-auto`. Each invocation creates new hosted work.

```sh
head=$(git rev-parse HEAD)
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref charlie/qa-rc24-parser-norun-20261104 -f reviewed_head="$head" -f cohort=pilot
```

For an existing original, fetch its `artifacts.json` and every corresponding `ID.zip` from the GitHub Actions artifacts API. The offline reader validates the server sizes and SHA-256 digests before reconstructing the result, all native checks, both calibration counters and the separately observed physical commands. The same procedure covers a qualified confirmation. Use its exact QA commit for `head`. The host needs Python 3.11+, zstd and compatible x86-64 Linux to run the original test ELF.

```sh
python3 -IB scripts/ruff-parser-test-norun/review.py pilot "$archive_dir" "$head" "$run" "$archive_dir/verified.json"
```
