# Native GNU qualification for sorted packed Git refs

This manual source-only job builds Rust Q `ed4d666c746f5ba92ac9d8086a934d1701aa6307`, the direct child of D `d95494a6a63c22222806c06e3d3aa0de504d8e8a`. For files up to 65,536 bytes Q preserves D's existing lookup. For larger files Q reads at most 65,537 bytes and searches complete rows in the bounded prefix only when the Git header declares the literal space-delimited `sorted` trait. A peeled line belongs to its preceding primary row. Oversized legacy headers and incomplete or out-of-prefix rows fall back to the existing donor selection. The source check has no timing or full-Ruff endpoint.

The frozen importer reopens the official D source job 41303656721, including both source artifact checksums, the complete 81-member E SDK, the D overlay and the original 12-test output. The 19,166-byte D and 20,380-byte Q Git packs contain nine objects each. The only changed product files are `compiler/rustc_incremental/src/persist/fs.rs` and `fs/tests.rs`. D and Q use the same stage0, CI LLVM, source paths, bootstrap arguments, Cargo 761 and stock Wild. Earlier streaming-reader P, source job 41323607555, remains a separate subject.

The original D source job has head `8f633d8fc21e453f4c81d81588b6dcab125bfeae` throughout this experiment. The source receipt test reopens its genuine recorded GitHub identity and rejects substituting either later packaging head. The preceding Q source run 41328071270 at `830181f5` is recorded separately. Only this checkout's own successful source job qualifies.

The worker builds Q with the original `./x` stage1 command. It runs all 13 rustc_incremental tests, transplants the unmodified new test onto D's production tree with a test-only name for D's literal cap, and requires the real assertion to fail with D returning `None` instead of the expected revision. It then restores Q, repeats all 13 tests, runs the original packed-cache, opt-out and missing-query-cache run-makes, and verifies the reassembled SDK against the first Q build. A partial job preserves its available artifacts. Source admission requires every step, both original ZIPs, all physical file identities, and both native test results. The workflow has read-only Actions and repository permissions.

One 16-vCPU GNU worker runs one stage1 bootstrap with a 32 GiB free-space floor and the inherited resource monitor. It temporarily holds E, D and Q SDKs (about 727 MiB each) and uploads only changed Q members. Prior P source qualification took 5m12s including 4m37s for its build/test step. The original worker ceiling remains 165 minutes.

## Read back the job

Acquire the two official artifacts once, in order `sorted-packed-ref-source-and-driver` and `sorted-packed-ref-sdk-and-resources`. From this exact QA checkout, supply their local paths plus an existing private temporary directory. The receiver also verifies the official run, sole job, attempt, stages and digests through read-only gh-auto.

```sh
python3 -ISB scripts/gnu-same-revision-donor/receive_source.py RUN JOB SOURCE.zip SDK.zip PRIVATE_TMP
```

For an offline content replay of the extracted official ZIPs, use `reopen.py SOURCE_RECEIPTS SDK_AND_RESOURCES` from the same script directory. The candidate slot retains the existing literal names `P/overlay` and `sdk/P.json`. Its recorded source is Q. To materialize the validated SDK from D, use the following command with a new private destination.

```sh
python3 -ISB scripts/gnu-same-revision-donor/overlay.py SOURCE_RECEIPTS/P/overlay SDK_AND_RESOURCES PARENT_D NEW_PRIVATE_Q
```
