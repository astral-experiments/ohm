# Ruff PEP 723 test executable on x86_64-unknown-linux-musl

This structural study compares the original and modified Ohm compilers on the complete Ruff merge that introduced four real PEP 723 unit tests. It has no timing or counter endpoint. The original source job built and verified both compiler roles, and both of its ordinary Ruff workers passed. Its two provider workers stopped before Cargo. The separate 188-visit provider run qualified all six fresh private/shared mechanism, signed-reader and strict-reader histories. The original held registration remains separately preserved. The exact source transfer, role hashes, official artifacts, prior refusals and two final 94-visit native receipts are bound in admission.json. [Historical Ruff merge](https://github.com/astral-sh/ruff/commit/672bb4edf04c84f8b0753346359daee4057158f2) [Source and ordinary Ruff](https://github.com/astral-experiments/ohm/actions/runs/41170783373) [Provider qualification](https://github.com/astral-experiments/ohm/actions/runs/41173218253)

The physical installation starts as parent adea62b64b plus the aware Cargo c18e91b514. Both historical arms share all 182 unmodified SDK regular inodes, including the frontend, Cargo, rustdoc, default linkers and target standard library/test. A single authenticated rustc driver is atomically changed between P and C (d52336754e). Before each history the study verifies all 183 files, the driver's digest and same-inode relationship to the admitted role, and an observed ELF loader open through `rustc +ohm -vV`. Every downloaded crate is compared to a checksum in the two true Ruff lockfiles. No cross-compiled Rust code, target cache or dependency products from the signed baseline are imported. [Candidate source branch base](https://github.com/astral-experiments/ohm-rust/pull/285) [Canonical source-qualification code](https://github.com/astral-experiments/ohm/tree/89a055549f4335e6e172f96c65d162dcd9cb1046/scripts/ohm-musl-ast-pair)

## Native histories

On one Linux x86-64 worker, run P then C in distinct initially empty Cargo outputs at identical visible paths. The registered visits are original, edited, unchanged, second unchanged, wrong semantics, invalid Rust, repaired and four independently empty controls (new, old, wrong semantics and invalid). Each command is `cargo +ohm test --locked --offline -p ruff_python_ast --lib --no-run --target x86_64-unknown-linux-musl -j4 --message-format=json`. No user flags, trust overrides, compiler wrapper, target linker override, or alternate Cargo profile are supplied. The user command contains no test execution. Separate invocations of its actual static executable list the complete inventory, run all 49 or 53 tests, and run the 4 exact historical tests plus a fixed existing control. Every successful Rust edit that changes or repairs the code must run the physical native linker for the test executable. Either settled visit may be fresh, compile or relink. The actual full/link-only compiler and target-linker rosters determine which occurred.

The semantic negative changes only production code so the first closing PEP 723 delimiter wins. The checked-in test expects the last. A successful build must produce a different ELF; the focused test and full suite must fail, while the other three added tests and the existing control pass. The independent empty wrong build must agree. A separate Rust type mismatch at the end of the genuine source must produce Cargo 101 with E0308 at its exact source range on both warm and empty builds. The repaired program must match the independently empty edited executable byte for byte. Current depfiles for both locked leaf crates must show the hard marker on P and v2 on C when compiled from empty. The observer saves complete physical kernel argv, raw stdout/stderr, the actual depfiles, complete executable bodies once per SHA, program inventories/verdicts, and final-link counts. It compares the complete ELF and error diagnostics within and across arms. A mismatch remains visible in the terminal and bars a common-output conclusion.

## Admission and run

Use an already authorized fresh Linux worker with Python 3.11+, git, rustup, GNU readelf, GNU native linker, strace, zstd, ordinary network access to GitHub and the locked registry during preparation, and the canonical QA repo's dependencies. Use the identical native environment to the source job. Reserve at least 8 GiB free after provisioning its SDK. Each signed reference used at most 150 MB of combined Ruff target/build state at a settled boundary; the new study retains separate outputs and unique executable bodies until readback. The harness checks for 2 GiB free before each ordinary call. In the first Actions step, operating from a read-only checkout of the exact QA commit:

```sh
python3 -IB scripts/ohm-musl-ast-pair/lookup.py \
  41173218253 89a055549f4335e6e172f96c65d162dcd9cb1046 >> "$GITHUB_ENV"
```

In the subsequent step, use all seven source and provider bindings returned by the first step. The authenticated transfer is artifact 13031197422 from source run 41170783373, SHA-256 `c7db74e02fbaa592c1bd6ede5f696de41bc3e34c42fc5387f0c77d6e81499d8c`. Both roles keep the same operational rustdoc; the independently rebuilt candidate rustdoc and all four documentation/driver combinations are separately authenticated. `HARNESS` points to this directory.

```sh
set -eu
export QA_ROOT="$RUNNER_TEMP/ohm-aarch64-linux-zmij"
python3 -IB scripts/ohm-musl-ast-pair/restore.py P
(cd "$HARNESS" && sha256sum --check SHA256SUMS)
python3 -IB "$HARNESS/run.py" --qa "$PWD" \
  --receipts "$RUNNER_TEMP/musl-ast/receipts" \
  --work "$RUNNER_TEMP/pep723-pair-work" --out "$RUNNER_TEMP/pep723-pair-results"
```

An optional `--ruff /path/to/full/ruff.git` supplies the two exact revisions from a read-only local donor. The default fetches the real merge and its parent. An optional `--archive-cache /read-only/registry/cache/SOURCE_ID` seeds only cryptographically matched raw source archives in the fresh Cargo home. The usual two registry-fetch commands still run. All Rust intermediates and link outputs begin empty for each role. The program generates both wrong variants only in its private checkout. Keep `out` even on failure. No hosted work was dispatched to prepare this component.

## Checks actually run during staging

`selfcheck.py --ruff <existing-Ruff-checkout>` verifies exact source trees, both locks, both production mutations, diagnostic bytes/line and the unmodified test module in the wrong-semantic state. The independent signed baseline exercised the actual kernel process/ELF and structural source case on five real user commands. The P/C harness's executable-oracle routine then re-opened both authentic signed executable bodies in RAM, ran both complete 49/53 suites and all exact selections, and checked the saved inventories. The preexisting signed reference is distinct from an actual case on P or C. The proposed negative program, candidate-freshness and cross-arm outcomes are unobserved until the full new study runs.

The first hosted attempt restored the exact SDK and stopped before the first Cargo invocation. Its transfer identity stores the independently rebuilt candidate rustdoc as a digest. The original source-build record stores digest, length and mode. The reader now joins those two records, including the original source member SHA-256 `91e99bcc12bda4e8786420718fd0e7b12d94f3a17de1bd63f6caac4738e35f27` from artifact 13030768539. The two Ruff revision records are read by name alongside their descriptive source notes. Study subjects, commands, comparison rules and the original admission remain fixed. [First attempt and sealed inputs](https://github.com/astral-experiments/ohm/actions/runs/41174155613)
