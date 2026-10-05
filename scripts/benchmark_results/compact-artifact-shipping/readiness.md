# Compact artifacts: current compiler evaluation

This follow-up evaluates a narrower compiler that retains self-contained compact
objects and removes the unused metadata-compression and external-store
experiments. The original study's 10.44% Ruff result came from changing a
benchmark-only inline helper. It did not describe an edit to an existing Ruff
function or all Ruff rebuilds.

The four-round comparison is complete: **416 primary commands**, with every
runtime oracle passing, and **81,113 independent audit checks**. It saved
19.10% of allocated build storage on uv and 13.92% on Ruff after the edit
sequence, versus baseline. The
[four-round results](four-round-results.md) report the rebuild costs, including
the synthetic Ruff inline-edit slowdown. These results use the frozen Cargo
`4a281305`; a separate confirmation with the rebased Cargo `6333daf7` is in
progress. The studies are not pooled.

## Compiler change

The candidate restores the original contiguous metadata decoder, memory-mapped
input, metadata discovery, and incremental-record reader. Thirteen affected
files are byte-for-byte identical to the pristine compiler. The removed indexed
metadata and external-store paths are unnecessary for the proposed format,
which stores compact object members alongside raw Rust metadata in ordinary
archives.

The complete archive scanner remains in place. Ordinary consumers can still
discover and materialize compact dependencies, including mixed archives and
thin archives. The change retains ordinary static-library exports, saved-link
replay, metadata-prefix reuse, and the atomic publication and hardlink fixes.
The Wild implementation is unchanged at `9179eb988df2676342192a24dc337cf9823e9d56`.

External probes on compiler `9546795cae23d424bec08487b4f3cace591efb5a`
measured 274 ordinary-archive scans per synthetic Ruff rebuild. Aggregate scan
times were 29.74, 28.26, and 29.72 ms; the enclosing materialization calls took
38.10, 36.38, and 37.93 ms. These instrumented runs include probe overhead and
are excluded from accepted performance measurements. They do not support the
scanner alone as an explanation for the earlier 277 ms excess, which was
measured with a different compiler binary. The candidate removes the unused
compiler paths as a group; this experiment does not isolate any one of them.

## Four-round matched comparison

The completed primary set contains 416 commands: two projects, four modes, four fresh
rounds, and 13 commands per cell. All four modes use Cargo
`4a2813050da607ca5cfe7b5cf3a17ba7c9676be1` and Wild `9179eb9`.

| Mode      | Compiler                                                                                            | Compact option      |
| --------- | --------------------------------------------------------------------------------------------------- | ------------------- |
| baseline  | Pristine `348339ddae4288ebb3af97d204b19479fef8f5f2`                                                 | Off                 |
| current   | Previous candidate `9546795cae23d424bec08487b4f3cace591efb5a`                                       | Off                 |
| storeless | Narrowed candidate, frozen patch `8c24f6cf911c0829de90e5ec49b0ae04598f00d983168c9e1d126bef1d555275` | Off                 |
| compact   | Same narrowed candidate                                                                             | Actual Cargo opt-in |

All user rustflags are empty. The compact arm uses
`-Zohm-compact-artifacts=yes`, allowing Cargo to select the bundled linker and
generate the compact, fast-compression, and full-metadata policy itself.
Each arm occupies each position once across the four round orders. Every pair
also runs in each relative order twice.

The source-only commit `3b84b46e3fb38f80246f744275c69fe608dfb2f3`
matches the frozen patch. Subsequent Rust commit
`54f8b75ac31207d47af50fc8c5bc9dc90f2457de` changes only the Cargo gitlink to
`0d39870c83ccf09a250e55d9dd13a83d606b72be`. That Cargo change removes obsolete
option checks; it does not change generated flags, metadata policy, or cache
fingerprints. This comparison uses the frozen Cargo `4a2813050` binary for
every arm. The later rebase and its separate validation are described below.

Each cell performs a clean build, a no-op, three synthetic inline edits, a
restore, three application-function edits, three dependency-function edits,
and a final no-op. The real edits change existing diagnostic or display strings:

| Project | Application function                                            | Dependency function                                                                           |
| ------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Ruff    | `report_error` in `crates/ruff/src/main.rs`                     | `UnusedVariable::message` in `crates/ruff_linter/src/rules/pyflakes/rules/unused_variable.rs` |
| uv      | Cache-directory output in `crates/uv/src/commands/cache_dir.rs` | Invalid package-name diagnostic in `crates/uv-pep508/src/lib.rs`                              |

After every build, the runtime checks the exact new cache-directory output or
diagnostic, its exit status, and the synthetic helper's return value. Ruff's
unused-variable check also verifies diagnostic code F841 and its source
location. These are real source changes with observable outputs, but they do
not represent every kind of development edit. In particular, uv's application
function belongs to its library module tree; it is not a binary-only edit.

The comparison retains eight build jobs, line-table debug information, uv
development optimization level 0, Ruff development optimization level 1, and
trusted local registry reuse. It records wall time, CPU time, sampled process
RSS, compiler invocations, and the allocation of the entire private build lane,
including its shared-build subtree and scratch directory. Disk figures
deduplicate hardlinked inodes and describe settled allocation, not peak disk
use or unique physical CoW extents. Compiler builds do not use production PGO
or BOLT.

The harness and an independent review were frozen before accepted measurement.
Rejected commands and partial runtime failures are retained. The four rounds
provide four fresh build-cache histories; the three sequential edits within a
round are not three independent repetitions. Results must expose round
variation and absolute seconds alongside percentages.

This is a new controlled comparison. Cargo, the baseline linker, flags, and
fixture sequence differ from the original study. A result matching the pristine
compiler does not by itself prove that removing these paths caused the old
10.44% regression to disappear: that attribution also requires the current
compiler to reproduce an excess within this matrix.

### Interruption and primary selection

The first attempt stopped at its frozen noise guard during uv's third round:
338 accepted commands followed by one rejected baseline clean build. That build
and its runtime checks passed, but three sampled intervals showed more than
0.5 cores of CPU usage outside the observed build tree. The monitor recorded
aggregate outside CPU, not historical process ownership; its source remains
unattributed. The guard was not relaxed.

Before collecting further timings, the continuation plan froze a complete-round
restart: keep the first 312 commands (all four Ruff rounds and the first two uv
rounds), retain but exclude the incomplete uv round's 26 accepted commands and
one rejected command, and run uv rounds three and four in fresh lanes with the
same mode orders. All 104 continuation commands passed. The resulting evidence
contains **443 raw commands, 416 primary commands, and 27 explicitly mapped
exclusions**. The interrupted attempt retains its failed state; no successful
completion receipt was invented for it. Selection depends on the round boundary
and frozen admission rules, not measured timing values.

The independent audit verified the original and continuation files, runtime
oracles, format guards, no-op identities, resource admission, selection mapping,
and all 70 comparison groups with their four-round distributions. It also
checked 2,669 transferred files by size and SHA-256. The sole summarizer repair
averages paired deltas directly instead of subtracting large floating means;
this removes a fractional-byte cancellation error. The prior summary and failed
precision check are retained; raw measurements and the auditor did not change.

### Portable evidence

The [matrix supplement](measurements/readiness/readiness-matrix.tar.gz),
[inventory](measurements/readiness/matrix-inventory.json), and
[package receipt](measurements/readiness/matrix-package.json) accompany the
unchanged [correctness bundle](correctness/readiness/current-cut-correctness.tar.gz).
The supplement includes the raw commands, exact primary selection, summary
history, monitor logs, harnesses, and independent auditor. Its archive contains
2,391 files and 907,265,855 uncompressed bytes; the 62,488,912-byte compressed
archive has SHA-256
`9832541221286816eac2055ae93c47c0b2811d0e83cc6dcd39ee7b561e3261a6`.
The [summary](measurements/readiness/readiness-summary.json) and
[audit receipt](measurements/readiness/independent-primary-audit.json) are also
available without extraction. Follow the [portable instructions](measurements/readiness/README.md) for the continued
study audit; it supersedes the static bundle's prospective uninterrupted-matrix
recipe without changing that sealed bundle.

An [independent fresh extraction](measurements/readiness/portable-review.json)
verified both archives and reran 73,105 portable audit checks, reproducing the
same primary selection, summary, and all 70 comparison groups. The full
81,113-check audit additionally verifies the 2,669-file transfer. The portable
bundle retains the static archive's explicit exclusion of five cache
bookkeeping files totaling 44 bytes; all source, runtime, timing, failure, and
selection receipts remain present.

## Rebased Cargo confirmation

The current Rust head `36f01299cd71f6c090150a80fe4a7babb6245a0b` differs from
`54f8b75a` only in its Cargo gitlink. The compiler sources, libraries, lockfile,
bootstrap, and workflows are byte-for-byte identical. Its new base similarly
differs from the measured pristine compiler only in that gitlink. The existing
compiler binaries therefore retain their measured source boundary; the rebase
does not require another compiler build to validate unchanged compiler code.

Cargo `6333daf7cf99cf80125234c9419cbd36e9bff81a` preserves the compact option,
metadata policy, flags, profiles, fingerprints, and cache admission. Its inherited
base changes the active dependency scheduler, however, so the old Cargo's
timings cannot establish current integration performance. A separate actual
Cargo build and installed default/compact smoke test precede a 156-command
confirmation: two projects, three modes (pristine, narrowed ordinary, narrowed
compact), two fresh rounds, and the same 13-command edit sequence.

The forward/reverse orders balance pair precedence; the ordinary candidate
occupies the middle position in both rounds. These are two independent cache
histories, with three sequential edits per edit phase, not six independent
rounds. All modes use the actual current Cargo and the same Wild. The original
fixture, profile, measurement, noise guard, and runtime oracles are unchanged.
This confirms the current integration; it does not isolate the causal effect
of changing Cargo from `4a281305` to `6333daf7`.

## Correctness and integration

The frozen compiler passed native Linux builds of rustc, rustdoc, and the
standard library, followed by both forced metadata/export suites (two passed,
none failed or ignored). Its actual compiler component tarball installs with
the matching standard library and Cargo. Installed ordinary and compact smoke
builds pass, and the package's compiler driver, Wild binary, capability marker,
and license notices match the recorded build. This is a component installation
rehearsal, not a full production PGO/BOLT release.

The same frozen source passed a macOS rustc/rustdoc/standard-library build, an
ordinary compile/link/runtime check, and clean rejection of compact mode on that
unsupported platform. Twelve metadata UI tests and nine public-hash/incremental
run-make suites also passed, with no failures or ignored cases and unchanged
compiler/standard-library bytes.

Fresh Linux lifecycle tests passed private/public edits, saved replay,
ordinary/compact toggles, doctests, shared-cache reuse, and cleanup. Native
alignment checks passed at 64 bytes, 4 KiB, and 16 MiB through BFD, LLD, and
static-library exports. A seeded Btrfs worktree remained usable with seven
donor paths hidden; its copied archive worked alone, and subsequent edits and
saved replay returned the expected values. Independent review checked these
receipts, the 26-state preflight, the recorded macOS binaries, and the
source-to-package bindings for Linux. The [correctness audit](audit-correctness.md)
records the complete scope and retained setup failures.

The [independent review](correctness/readiness/review.md) and
[sealed evidence bundle](correctness/readiness/current-cut-correctness.tar.gz)
include the frozen harness, source patch, Linux/macOS logs, and provenance.
Fresh extraction verifies the complete inventory, 1,271 preflight assertions,
and 314 correctness assertions. The archive's README explains how to rerun
those receipt audits without the original machine, credentials, or binaries.

All eight enabled Cargo CI checks pass at `6333daf7`, including the Linux and
macOS Cargo suites; optional APFS replay was not selected. Compiler CI at
`36f01299` still stops in all three jobs at the missing read-only source-App
client ID, before formatting, tidy, or compilation. Local validation is separate
from that incomplete CI coverage. No credentials or release defaults were
changed.
