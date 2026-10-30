# Rebuilding Ruff after a real lint-rule edit

Teaching rustc that the complete AArch64 instruction `svc 0` cannot read assembler files reduced the first unchanged Ruff CLI build from 138.43 to 35.66 billion user instructions. The median paired reduction was 3.882× across 12 blocks in a randomized, balanced order. The same command took 12.39 versus 3.99 seconds. The real edit changed Ruff's PLE0643 verdict on a starred tuple. [Ruff edit](https://github.com/astral-sh/ruff/commit/193984681ef7185c90b548c27b0ac6326908f2ec) · [Original paired runs](https://github.com/astral-experiments/ohm/actions/runs/41104410375)

| Command | Metric | Pairs | Parent median | Patched median | Median paired ratio | 96.14% interval | One-sided p against 2× |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First unchanged build | B instructions | 12 | 138.429 | 35.659 | 3.882× | 3.881–3.883× | 1/924 |
| First unchanged build | s | 12 | 12.390 | 3.986 | 3.067× | 2.606–3.590× | 1/924 |
| First unchanged build | CPU s | 11 | 22.832 | 4.523 | 5.048× | — | — |
| Edit to the Ruff lint rule | B instructions | 12 | 147.500 | 71.030 | 2.077× | 2.076–2.077× | 1/924 |
| Edit to the Ruff lint rule | s | 12 | 13.898 | 9.443 | 1.454× | 1.317–1.566× | 924/924 |
| Edit to the Ruff lint rule | CPU s | 11 | 25.742 | 10.749 | 2.395× | — | — |
| Edit plus first unchanged build | B instructions | 12 | 285.937 | 106.695 | 2.680× | 2.679–2.680× | 1/924 |
| Edit plus first unchanged build | s | 12 | 26.007 | 13.367 | 1.943× | 1.710–2.118× | 651/924 |
| Edit plus first unchanged build | CPU s | 11 | 48.263 | 15.108 | 3.195× | — | — |

The command was `cargo +ohm build -p ruff --bin ruff --target aarch64-unknown-linux-gnu --locked --offline -j4 --message-format=json` on an x86-64 Linux host. Both roles used the same experimental Cargo #301 and the same 118 remaining SDK files. The only change was the rustc driver. All 372 Cargo units were enrolled on existing dev-profile defaults with ordinary incremental compilation. Each role trained its own private build directories. The paired ratios use within-block observations. The parent and patched columns are separate medians.

The hardware event was Linux `PERF_COUNT_HW_INSTRUCTIONS` in user mode. Every counted block passed calibrated loops in the initial process, child, grandchild, two independent descendants, a second executable and one or two pthreads. At least 99.5% of enabled time had to be scheduled on the counter. Elapsed time covers those same Cargo commands. Tree CPU time qualified on 11 of 12 blocks. The two initial screen pairs are excluded. Each 12-pair interval uses the third and tenth ordered ratios. The one-sided randomization p value enumerates all 924 assignments with six of each role order. The 2× tests apply separately to their listed endpoints. [Registered order and endpoints](./registered-pairs.json) · [Counter implementation](../../watch.c)

The separate kernel execution trace of the experimental Cargo #301 run recorded 19 full rustc invocations on the real edit and 19 on its immediate repeat with the parent driver. The patched driver issued four and three respectively. Both toolchains still linked the Ruff executable. On a separate Cargo integration built on top of released #294, the corresponding counts were 17 to two on the edit and 17 to one on the repeat. The signed `-20` Cargo has no fast path for the new marker. The release integration retains the older writer's native-input limitations. [Original compiler and linker traces](https://github.com/astral-experiments/ohm/actions/runs/41099028701) · [Separate released Cargo and compatibility results](../release-reader-compatibility/)

The edited, repeated and repaired Ruff binaries matched empty builds within each toolchain. Their executable text also matched across toolchains. QEMU checked the original false positive, the edited verdict, a genuine out-of-bounds access and a valid access. The separate invalid Rust edit failed with E0425. Each of the 12 paired blocks also retained six full AArch64 ELF reads from independent old, edited and empty builds. On an additional `ty_project` end-to-end test edit, the physical compile count fell from five to three on edit and from four to two on repeat. That comparison verifies work performed and the real test binary.

The literal instruction changed exactly one of 26 dep-info controls per compiler. A neighboring `.incbin` kept the hard rebuild marker. A runnable syscall program agreed with `std::process::id()` on both arms. Another 408 actual Cargo builds checked real linkers and native programs across three reader versions, higher-priority libraries, same-inode replacements, malformed archives and reader migrations. [Direct compiler outputs and native readbacks](./safety/)

The median allocated footprint of the private target and build directories after the edited and repeated builds was 2.431 GiB on the parent and 2.418 GiB with the patch. Every measured build directory had 42 incremental crate directories, each with exactly one session. Physical allocation counts each inode once across both roots.

To recompute all paired results from the retained original clocks, Cargo rosters, storage censuses and native-build observations, run the following here with Python 3.11 or newer and zstd.

```sh
python3 -IB verify.py
python3 -IB safety/verify.py
```

On Linux, `python3 -IB verify.py --complete-archives` additionally fetches the source-bound Actions ZIPs and reopens all 72 original ELF files while the archives remain available. `registration.json` records both the full ZIP and compact record hashes. To repeat the experiment, dispatch the source workflow on its QA branch with `phase=holdout`. The pinned workflow records the exact source, schedule and compiler capsule. [Workflow](https://github.com/astral-experiments/ohm/blob/61127b2e9531769dea162b31a267d86a0368b479/.github/workflows/ci.yml)
