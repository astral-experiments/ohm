# Native Apple silicon Ruff build after a Python-version edit

These hosted Apple measurements ran with `CI=true`. The local Ruff compilers ran without rustc incremental compilation. Cargo could reuse finished artifacts between commands. [Original compiler arguments and profile verification](../native-apple-cargo-profile-v1)

On a single fixed checkout, the first unchanged `cargo +ohm build -p ruff_python_ast --locked --offline -j4 --message-format=json` took **157.2 ms with the parent and 41.6 ms with the child**. The median of the twelve independent paired ratios was **3.820×**. The prespecified two-sided 96.14% median interval was **3.583–3.999×**. All twelve ratios exceeded 2 (range 3.473–4.410). The one-sided test against a sharp 2× effect gave **1/924** across the 924 balanced allocations. [Native paired job](https://github.com/astral-experiments/ohm/actions/runs/41048813491) · [Frozen QA source and protocol](https://github.com/astral-experiments/ohm/tree/3290af7b378353c6a2808487bc93ed587ab024bb/scripts/ohm-apple-zmij)

| Whole Cargo command in the confirmation | Parent median | Child median | Median paired speedup | 96.14% interval |
|---|---:|---:|---:|---:|
| First build after the edit | 1.959 s | 1.845 s | 1.060× | 1.035–1.088× |
| First unchanged build (primary) | 157.2 ms | 41.6 ms | 3.820× | 3.583–3.999× |
| Further unchanged build | 155.1 ms | 39.2 ms | 3.982× | 3.844–4.062× |

The job applied Ruff commit `ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0` on its actual parent, using one checked-out branch and Cargo’s CI profile. Each independent installation started empty, compiled the old revision, then measured three consecutive foreground Cargo calls with a blocking wait. The timings exclude the source edit itself, the later semantic readers and the native observation runs. Two separate mirrored pairs first passed the 2× gate at 3.901× and 3.491×. The twelve-pair confirmation then ran in a fresh set of installations with six parent-first and six child-first. There are **14 independent pairs across the two separately reported cohorts, 44 total installations, 160 closed Cargo phases and 84 timed commands**. Each confirmation pair contributes one primary observation. [Ruff edit](https://github.com/astral-sh/ruff/commit/ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0)

## What ran

The actual Apple-silicon Namespace runner used Darwin 24.6.0, Xcode 16.0 and signed `-20` Cargo `2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c`. Rust was a matched pair of source-built stage1 compilers on `2035696c5316079f5b2e4373aee834839aac97e9` and `444c0273a2e2bc0b161e988d43c882349bc2d7a6`. Both used the same stage0, LLVM, flags, path and version stamp. Of the 2,466 captured runtime/source files, only the compiler dylib changed, from `0fb95e95f6b3bc1fbf2030989915c93de49c98361e72970b9ac886c8f07eeb23` to `fc7063909886717c0b605bca7a465169b9c969c0256a301fec7bb3fae9974519`. A native object emission verified each loaded dylib with dyld. Signed Cargo and all host std files matched. The tested architecture and stage1 build configuration bound the result. [Compiler comparison](https://github.com/astral-experiments/ohm-rust/compare/2035696c5316079f5b2e4373aee834839aac97e9...444c0273a2e2bc0b161e988d43c882349bc2d7a6)

| Outside-clock kernel execs | Parent | Child | Apple linker |
|---|---|---|---|
| Cold ordinary build | 39 full rustcs | 39 full rustcs | 8 per arm |
| Real edit | `ruff_python_ast`, `zmij` | `ruff_python_ast` | 0 |
| Each unchanged build | `zmij` | None | 0 |

The parent reports three dirty typed artifacts on both unchanged commands (`zmij`, `compact_str`, `ruff_python_ast`). The kernel saw only the `zmij` compiler. The child reports all 39 fresh. Both arms had zero link-only jobs and zero native links on the edit and both repeats. Apple Endpoint Security recorded compiler and Xcode linker execs outside the timed window, with separate calibrated reader links. The CPU burn at process, child and grandchild depth calibrated the elapsed CPU totals. Whole-Cargo first-repeat CPU medians were 180 and 20 ms at 10 ms reporting granularity. None of the 18 raw Darwin timer records reported retired instructions.

## Behavioral controls

* Unmodified signed `-20` showed one real `zmij` compilation in the cold build and each unchanged build. Removing only its AArch64 vector-register assembly comment gave 1/0/0. Restoring it gave 1/1/1 again. This isolated the input before the paired source-build trial. The normal Rustup/Cargo entry point was retained. [Signed Apple acquisition](https://github.com/astral-experiments/ohm/actions/runs/41048321533)
* Readers compiled against the actual returned Ruff artifact produced `3.14 3.14 3.10` before and `3.15 3.15 3.11` after the edit. The invalid edit produced E0425 in both arms. Restoration produced the clean behavior.
* All **72/72** measured confirmation results (12 pairs × 2 arms × 3 endpoints) matched their own independently empty edited reference on the **16 named Mach-O object bodies, the raw reader executable, and lib.rmeta-link**. **0/72** matched on `lib.rmeta` or the entire rlib. The separate screen reproduced the same distinctions on all 12 comparisons.
* Both roles, before each native timing cohort, consumed a real static C library with values 17 then 29. A malformed or missing archive failed with Cargo 101. Restoring it yielded the same executable hash as the independently empty 29 case. Signed and source-built SDKs each compiled an actual procedural macro, expanded it in a separate native compiler, and executed the result 3. The child also passed the checked-in NEON / rejected-modifier / assembler-input run-make test.
* Earlier QA attempts produced no performance observations. They exposed Rustup/clang calibration assumptions, two lexical temporary-path checks, bootstrap source symlinks that reached back into stage1, and a `library/std`-only build missing the host `proc_macro` crate. The corrected QA builds the complete `library` sysroot. Original GitHub attempts remain separately visible, including the two source-bootstrap first failures. [First source snapshot](https://github.com/astral-experiments/ohm/actions/runs/41042423082) · [Incomplete sysroot](https://github.com/astral-experiments/ohm/actions/runs/41046945525)

## Independent verifier

Run from this directory with Python 3.10 or later. The default mode uses only the compact observation table and the standard library. It checks the native rosters, semantic results, comparisons with empty builds, all recorded per-pair clocks and the exact randomized test.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
```

For a deep replay, supply the two original Actions artifact ZIPs in signed-then-qualified order. Use an authenticated checkout of the packaging repository to obtain them while hosted artifact retention is active. On macOS use `shasum -a 256 -c SHA256SUMS`.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/12972779716/zip > signed.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/12974003361/zip > qualified.zip
python3 -IB verify.py --raw signed.zip qualified.zip
```

The deep replay checks the original ZIP digests and CRCs, rebuilds the portable projection from all 179 and 1,371 members, matches real kernel-event paths and code-directory identities for the calibrated Xcode linker, rereads Cargo stdout and captured files, and requires the projected data to equal the compact table byte-for-byte after canonical serialization. The table includes raw per-command receipt digests and full compiler argv commitments. Original artifact SHA-256 values are `7c4cfa668f1a58bfe3092051a70b86197092efa400b1fa6a72599d836d51c2b6` (signed) and `43e46340f95c438d2ea149f19c5305a144fde3d2f117a74f3262a826eebcf825` (qualified).
