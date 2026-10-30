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

Separate kernel execution traces on experimental Cargo #301 recorded 19 full rustc invocations on the real edit and 19 on its immediate repeat with the parent driver. The patched driver issued four and three respectively, plus one link-only rustc for Ruff on each command. Both toolchains ran the host linker for a build script and the GNU AArch64 linker for the Ruff executable on both commands. [Parent trace](https://github.com/astral-experiments/ohm/actions/runs/41096470630/artifacts/12996043953) · [Repeated parent trace](https://github.com/astral-experiments/ohm/actions/runs/41099907460/artifacts/12997643647) · [Patched trace](https://github.com/astral-experiments/ohm/actions/runs/41099028701/artifacts/12999076256)

On a separate Cargo integration built on top of released #294, the full rustc counts were 17 to two on the edit and 17 to one on the repeat. The signed `-20` Cargo has no fast path for the new marker. The release integration retains the older writer's native-input limitations. [Released Cargo and compatibility results](../release-reader-compatibility/)

The edited, repeated and repaired Ruff binaries matched empty builds within each toolchain. Their executable text also matched across toolchains. QEMU checked the original false positive, the edited verdict, a genuine out-of-bounds access and a valid access. The separate invalid Rust edit failed with E0425. Each of the 12 paired blocks also retained six full AArch64 ELF reads from independent old, edited and empty builds. On an additional `ty_project` end-to-end test edit, the physical compile count fell from five to three on edit and from four to two on repeat. That comparison verifies work performed and the real test binary.

The literal instruction changed exactly one of 26 dep-info controls per compiler. A neighboring `.incbin` kept the hard rebuild marker. A runnable syscall program agreed with `std::process::id()` on both arms. Another 408 actual Cargo builds checked real linkers and native programs across three reader versions, higher-priority libraries, same-inode replacements, malformed archives and reader migrations. [Direct compiler outputs and native readbacks](./safety/)

The median allocated footprint of the private target and build directories after the edited and repeated builds was 2.431 GiB on the parent and 2.418 GiB with the patch. Every measured build directory had 42 incremental crate directories, each with exactly one session. Physical allocation counts each inode once across both roots.

## Independent repetition

Twelve new workers repeated the original schedule with the same Ruff edit, pinned Cargo, parent and patched rustc drivers, and byte-identical measurement job. The two cohorts used 24 distinct GitHub runner IDs. The table reports the second cohort alone. [Second run](https://github.com/astral-experiments/ohm/actions/runs/41123332513) · [Raw clocks and native readbacks](./repetition-41123332513/) · [All paired results](./repetition-41123332513/results.json)

| Build | Parent → patched user instructions | Paired speedup (96.14% interval) | Parent → patched elapsed | Paired speedup (96.14% interval) |
| --- | ---: | ---: | ---: | ---: |
| Real edit | 147.512B → 71.039B | 2.0764× (2.0762–2.0768) | 13.928 s → 9.626 s | 1.451× (1.300–1.547) |
| First unchanged | 138.436B → 35.657B | 3.8827× (3.8813–3.8832) | 12.767 s → 3.952 s | 3.122× (2.991–3.413) |
| Edit plus first unchanged | 285.950B → 106.698B | 2.6800× (2.6797–2.6805) | 26.810 s → 13.558 s | 1.952× (1.779–2.148) |

All 12 workers passed the hardware instruction calibrations. The balanced randomization test against 2× gave p = 1/924 for each instruction endpoint and for elapsed time on the first unchanged build. Eight workers passed the separate CPU calibration. Among those eight, the median paired CPU speedup was 2.37× on the edit, 5.18× on the first unchanged build and 3.18× for both together.

Each worker produced six full AArch64 ELF readbacks. All 72 were checked against their recorded bytes and executable text. The edited and repeated Ruff builds agreed with their own empty builds and QEMU reproduced the lint verdicts. The invalid-edit and repair controls ran in the separate traced builds. Median allocated space was 2.431 GiB on the parent and 2.418 GiB with the patch, with one incremental session for each of the 42 crate directories in every arm.

To recount the second cohort from this directory, run the following offline. Add `--complete-archives` to reopen the full original ELF bytes while the hosted archives are retained.

```sh
python3 -IB verify.py --records repetition-41123332513 \
  --run 41123332513 --head 927e20bcad028e5ed4290a58bd330a258ee5da41
```

## Rerun the benchmark

To recompute all paired results from the retained original clocks, Cargo rosters, storage censuses and native-build observations, run the following here with Python 3.11 or newer and zstd.

```sh
python3 -IB verify.py
python3 -IB safety/verify.py
```

On Linux, `python3 -IB verify.py --complete-archives` additionally fetches the source-bound Actions ZIPs and reopens all 72 original ELF files while the archives remain available. `registration.json` records both the full ZIP and compact record hashes. To repeat the experiment, dispatch the source workflow on its QA branch with `phase=holdout`. The pinned workflow records the exact source, schedule and compiler capsule. [Workflow](https://github.com/astral-experiments/ohm/blob/61127b2e9531769dea162b31a267d86a0368b479/.github/workflows/ci.yml)

The short route uses the original prebuilt toolchains. GitHub expires the first of those build artifacts on November 2, 2026. The clocks, unit inventories, correctness records and storage measurements checked into this directory can be recounted offline after that date. From an authenticated Ohm checkout, record the QA revision before dispatching a fresh cohort. Set `GH_BIN=gh` if your authenticated GitHub CLI is named `gh`. [Original toolchain build inputs](../../../ohm-aarch64-versioned/qualified-builds.json)

```sh
qa_commit=$("${GH_BIN:-gh-auto}" api 'repos/astral-experiments/ohm/commits/charlie%2Fqa-gnu-ruff-syscall' --jq .sha)
"${GH_BIN:-gh-auto}" workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-gnu-ruff-syscall -f phase=holdout
```

Set `holdout_run` to the numeric ID of that run. Once its 12 jobs succeed, run the following from this evidence directory. The collector verifies the run used the recorded QA commit, reads all 72 original ELF files, and writes this cohort's results to a separate directory.

```sh
python3 -IB collect.py --run "$holdout_run" --head "$qa_commit" "fresh-$holdout_run"
```
