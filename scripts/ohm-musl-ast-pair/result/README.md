# Linux musl Ruff AST qualification

The first unchanged `cargo +ohm build -p ruff_python_ast --lib --target x86_64-unknown-linux-musl` after the upstream Ruff visitor edit ran `zmij`, `compact_str` and `ruff_python_ast` on the parent. The candidate reused all 39 units. Neither role invoked a linker on that build. A second unchanged command repeated both rosters. The edited build went from three full target rustcs to one. On `cargo test --lib --no-run`, both unchanged visits went from three full rustcs to one link-only rustc. Each invoked the genuine GNU linker. The candidate still compiled and linked the test executable on the edit and repair. No test execution was timed. [Source and ordinary jobs](https://github.com/astral-experiments/ohm/actions/runs/41170783373)

The corrected visitor observed each `elif` predicate once and both clauses, compared with twice and zero before the fix. The edited, repeated, repaired and independent empty builds produced the same 4,229,656-byte visitor. Invalid code failed with E0425. The check also compares all 54 test names and the complete test executable across states and roles. The ordinary private-plus-shared allocated bytes after the first unchanged build were 162,213,888 and 160,485,376, counting hardlinked files once. These are structural and correctness results. The separate counterbalanced hardware study determines the workflow cost.

Each native provider layout ran 42 mechanism commands, 26 migration commands with signed Cargo #294 and 26 with strict Cargo `761ea115`. All 94 warm/empty pairs across both layouts matched on exit, native outcome and full executable. Both older readers read an authenticated pre-existing v2 record before its first write, rebuilt the producer and rejected the malformed higher-priority archive with GNU `ld`. There were 29 distinct dep-info bodies on each worker. The earlier source run's two provider jobs stopped before any Cargo visit. The subsequent ext4 run passed the shared matrix and stopped after 90 private visits because its observer rejected a failing rustc thread in an expected link failure. The final ext4 run passed both matrices. The exact private thread-exit qualification and both original ZIPs are preserved by the adjacent verifier. [Final providers](https://github.com/astral-experiments/ohm/actions/runs/41173218253) [Earlier ext4 run](https://github.com/astral-experiments/ohm/actions/runs/41172642028)

## Reopen without GitHub or installed Ohm

On x86-64 Linux, use Python 3.11 or newer, `b3sum`, `sha256sum` and an executable temporary directory. The verifier executes only the hash-enrolled static fixture programs. The solid archive retains complete older and corrected Ruff visitor programs, the actual test executable, four hard-rebuild fixture programs, all seven unbundled-provider native programs, and the raw files behind all 60 retained Cargo dep-info paths/content keys. It includes per-phase compiler/linker rosters, program verdicts, fetch coordinates, and per-suite readback. The full strace streams and compiler bootstrap kit are in the original Actions artifacts. `TMPDIR` may be set to an existing writable and executable directory.

```sh
cd scripts/ohm-musl-ast-pair/result
sha256sum --strict --check SHA256SUMS
python3 -IB replay.py
```

To reconstruct the packet from the four original ZIPs, download them without unpacking. The `--archives` path contains `41170783373/ordinary-{P,C}.zip` and `41173218253/native-{private,shared}.zip`. `replay.py` verifies their complete SHA-256 values before opening any captured program. This route additionally requires `zstd` to decode the original real Ruff executables.

```sh
python3 -IB replay.py --archives /absolute/path/to/downloads
```

The source and ordinary records came from `42ab8393dcb7da2e468ed336933fa90c392d58a5`. The final provider records came from `89a055549f4335e6e172f96c65d162dcd9cb1046`. Both restored the original 183-file kit, archive SHA-256 `c7db74e02fbaa592c1bd6ede5f696de41bc3e34c42fc5387f0c77d6e81499d8c`, with all 182 non-driver members identical. Run the following command at the provider SHA with authenticated read access to obtain the seven verified source and provider bindings while the original Actions artifacts are retained. [Native source and restoration](https://github.com/astral-experiments/ohm/tree/42ab8393dcb7da2e468ed336933fa90c392d58a5/scripts/ohm-musl-ast-pair) [Acceptance verifier](https://github.com/astral-experiments/ohm/tree/89a055549f4335e6e172f96c65d162dcd9cb1046/scripts/ohm-musl-ast-pair)

```sh
python3 -IB scripts/ohm-musl-ast-pair/lookup.py 41173218253 89a055549f4335e6e172f96c65d162dcd9cb1046
```
