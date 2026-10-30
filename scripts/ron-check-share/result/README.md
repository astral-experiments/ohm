# A repeated Ruff check compiles Ron and can replay a stale type error

On signed Ohm `1.99.0-21`, an unchanged Linux x86-64 check of
`ty_project` ran one real rustc for Ron. It spent **69.13% of the whole
command's retired user instructions** in that compiler. Deleting every Ron
instruction would give an upper bound of **3.24×** on this check. Reaching
2× would require avoiding at least 72.33% of Ron's instructions. The edit
plus its first repeat had a 1.79× upper bound. These are observations of a
single workflow and algebraic upper bounds. A faster or safe implementation
was outside this experiment.

The workload used Ruff `93526150df078af7dd8fc4226cdcc469539d2001` and
reversed the complete historical change `32c5cd5daba51d9c3da691c5b43afa6a7a4bb731`
to preserving known module owners in ty_project's uv dependency metadata.
The 338-unit test check selected exactly one Ron 0.12.0 with its default and
standard-library features. It returned 303 artifact records. The separate
signed graphs for ty_server's test check (331 units) and ruff_db's (209)
selected no Ron. [Historical Ruff edit](https://github.com/astral-sh/ruff/commit/32c5cd5daba51d9c3da691c5b43afa6a7a4bb731)

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
```

| Visit | Whole-command user instructions | Ron user instructions | Ron fraction | Full rustcs | Native links |
| --- | ---: | ---: | ---: | --- | ---: |
| Historical edit | 5,410,070,751 | 1,756,839,615 | 32.47% | Ron, ty_project | 0 |
| First unchanged | 2,541,466,454 | 1,756,795,215 | 69.13% | Ron | 0 |

The outer kernel observer authenticated native Cargo and rustc by device,
inode and complete NUL-delimited argv. It enrolled the Ron subtree before
its first user instruction and covered its worker threads. All 28
calibration visits met the seven predeclared scope checks and every PMU
read had equal enabled and running times. The selected counter included
the direct, forked, multigeneration, exec and threaded fixtures while
excluding an independently sized sibling. The unchanged Ron compiler
emitted metadata with its foreign-span sentinel and had no incremental
option. The workspace rustc on the edited visit was incremental.
[Original run and failed recovery gate](https://github.com/astral-experiments/ohm/actions/runs/41139480769/job/124349977576)

## Exact repair kept the failed check's diagnostics

In the first run a deliberately invalid line in `ty_project/src/lib.rs`
returned 101 and emitted E0308. Restoring the source bytes produced exit
0 and a successful final Cargo JSON record, alongside the identical
E0308. We kept that gate failed. Separate raw stdout and stderr files
identify the two independent processes. The following 45 unscored
diagnostic visits then examined signed -21, the same -21 with
`-Zohm-defaults=no`, and signed -20. Each had fresh private build trees
and empty same-source controls. Both official packages used Cargo
`2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c`. The -21 compiler was
`c79998a5cd143c445a4b2528f20953b176a65c5d`.
[Recovery and compiler phase run](https://github.com/astral-experiments/ohm/actions/runs/41140013497/job/124351732232)

| Source and invocation | Signed -20 and -21 | Same signed -21 with defaults off |
| --- | --- | --- |
| First type error | 101, correct E0308, real ty_project rustc | 101, correct E0308, real ty_project rustc |
| Return to original valid source | 0, **stale E0308**, Ron alone | 0, no errors, real ty_project rustc |
| Unchanged valid, normal human output | 0, **stale E0308 and prior invalid line** | 0, no errors |
| Unchanged valid, fresh JSON process | 0, **same stale E0308** | 0, no errors |
| Reintroduce first invalid source | 101, correct E0308 | 101, correct E0308 |
| A different invalid source and an unchanged repeat | Both 101 with the new source line | Both 101 with the new source line |
| A different valid edit, return to original, and empty builds | All 0, no errors | All 0, no errors |

The failed ty_project compiler left an empty short success fingerprint
and a 2,866-byte `fingerprint/output-test-lib-ty_project`. On exact
repair, Cargo accepted unchanged Ron metadata, skipped Insta and then
skipped ty_project for changed dependency fingerprint `UnitIndex(91)`.
Cargo restored the 16-byte success fingerprint while keeping the failed
output. An independent per-process system call trace records native
Cargo opening that file, reading all 2,866 bytes and reaching EOF. Its
three raw compiler messages were the type error, abort summary and
failure note. Cargo emitted the original error and failure note after
ordinary color handling. The unchanged human invocation had its
diagnostic logging disabled and rendered the deleted source line.

The repaired `lib.rs` occupied the same inode, with a new timestamp and
the original 47,812 bytes. The invalid 47,853-byte source and independently
changed 47,867-byte invalid source had distinct recorded hashes. All
successful test-check roots returned zero-byte test metadata. Process
exits, actual source bytes and error spans are the semantic controls here.
The different valid source forced a real ty_project compiler and deleted
the stale message cache on both releases.
[Signed Cargo early-cutoff replay](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/compiler/mod.rs#L1429-L1478)
[Signed Cargo's comparison after a failed build](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/compiler/fingerprint/mod.rs#L3174-L3195)

## Whole Ron self-profiles

A separate fresh target and shared directory recorded full native rustc
self-profiles while compiling only Ron with extra instrumentation. Each
ran 16 procedural-macro calls and emitted zero LLVM codegen modules.
The table uses rustc's elapsed-time phase records in milliseconds.
The root-thread intervals for the four phases from interface checking
through borrowing were disjoint in both native profiles. These phase
observations do not apportion the ordinary command's hardware instructions.

| Phase | Training Ron | Repeated Ron |
| --- | ---: | ---: |
| Macro expansion | 22.81 | 22.08 |
| Type-check interfaces | 42.86 | 69.24 |
| Generate crate metadata | 24.91 | 19.89 |
| Type-check bodies | 115.23 | 121.41 |
| MIR borrow checking | 105.51 | 115.26 |
| Whole profiled rustc | 423.91 | 432.19 |
| Raw events | 248,414 | 248,612 |

Later interface, metadata, body and borrow checking totalled 325.81 ms in
the repeated profile. Work available to a behavior-preserving optimization
depends on proving the results of the real macros and their span provenance.

## Offline verification

From the packaging checkout, the standard-library readers below verify
this packet and reproduce both stored summaries. The `primary.zip`
digest is GitHub's exact original artifact digest. The solid XZ contains
all 428 records from the second GitHub ZIP, including full native profiles
and the original per-command streams. Nested gzip is unwrapped for
cross-visit compression. Its embedded index binds every original member
size and SHA-256 and every retained payload size and SHA-256. The two
archive readers returned identical results on the source ZIP and solid XZ.

```sh
cd scripts/ron-check-share/result
sha256sum --check SHA256SUMS
python3 -IB verify_primary.py | cmp - primary.json
python3 -IB verify_recovery.py | cmp - recovery.json
```

Original primary ZIP 13017707410 has 309,996 bytes and SHA-256
`9e3a59e091c467c5139532dfb09cd8765eef343c938c0680e75da3ec2282ce3e`.
Follow-through ZIP 13018966532 has 14,345,013 bytes and SHA-256
`ba90978f8720a4d8d8d54a12f5e970938d646dd85377e6a5be03bf3d28bd2d0c`.
The primary workflow is `6386ed93a6e4aabff744e92d70846f4e6170fceb` and
the separate diagnostic/profile workflow is
`970c92d361d69406b3cd35a70e72cb60d17d0539`.
