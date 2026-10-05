# Initial compact-artifact study

This page preserves the original 312-command study and its adoption hold. Its
compiler, linker, Cargo, and synthetic edit fixtures differ from the
[current evaluation](readiness.md); these are historical results.

## Initial measurement design

The frozen matrix has 312 build commands: two projects, four modes, three fresh
rounds, and 13 commands per cell. Each cell includes a clean build, two no-ops,
three direct edits, a restore, three private-library edits, and three inline edits.
These edits change constants in benchmark-only code injected into each project:
the binary's entry point, a non-inlined library helper, and an inlined library
helper, respectively. The rebuilt binary must return the new value. They test
rebuild and cache invalidation behavior, but are not edits to existing Ruff or
uv functions; the inline result does not describe all edits in either project.
Mode order reverses in the middle round. Sequential edits share cache history; the
summary exposes per-round means rather than treating all nine edits as
independent runs.

| Mode            | Compiler            | Linker                     | Artifacts                                                   |
| --------------- | ------------------- | -------------------------- | ----------------------------------------------------------- |
| baseline        | Pristine Ohm source | Pinned shipped Wild 0.10.0 | Ordinary                                                    |
| standard        | Candidate source    | Candidate Wild fork        | Ordinary                                                    |
| compact-raw     | Candidate source    | Candidate Wild fork        | External-store objects, raw metadata, repaired prefix reuse |
| compact-archive | Candidate source    | Candidate Wild fork        | Self-contained compact archives with full raw metadata      |

`standard` to `compact-archive` isolates the format and required metadata policy.
`baseline` to `compact-archive` includes the compiler and linker changes. The
external-store arm is a diagnostic control for the new container design.

All arms use the same installed Cargo revision. Its admission rules permit the
format flags, so this does not disable shared registry caching. The actual new
Cargo option is validated separately by the lifecycle and worktree harnesses.
The launch preflight verifies the absence of compiler-logging variables, which
would otherwise change cache admission.

The workloads use uv at development opt-level 0 and Ruff at global development
opt-level 1, with line-table debug information and eight build jobs. Incremental
graph compression is disabled. These compiler builds do not use production PGO
or BOLT; absolute timings are not installed-release performance claims.
All arms use `CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and
`CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all` for trusted local development.

Storage is the whole lane: private target, shared build directory, incremental
state, scratch files, and any external store. Census deduplicates hard links and
reports both logical bytes and allocated filesystem blocks. CPU and sampled
process-tree peak RSS accompany wall time. Every command must pass its runtime
oracle, and each clean build must prove the requested on-disk format. An
unrelated compiler or sustained outside user CPU invalidates the run.

## Initial results and decision

All **312/312 commands** were accepted across 24 cells. The independent audit
passed **14,541 checks**, including every runtime oracle, all 24 format guards,
216 edit commands, 48 no-op identities, binary/configuration provenance, and
every aggregate and per-round calculation. There were no exclusions or
post-measurement admission changes. See the [audit](measurements/audit-shipping.md)
and [machine-readable summary](measurements/shipping-summary.json).

The following storage figures are mean **settled allocation after the edit
sequence**, across three fresh rounds. They count the complete build lane,
including the private target and shared cache, and deduplicate hard links. They
are not peak disk use, final executable sizes, or the size of the toolchain.

| Project | Baseline allocated | Compact allocated | Reduction |
| ------- | -----------------: | ----------------: | --------: |
| uv      |          3.457 GiB |         2.801 GiB |     19.0% |
| Ruff    |          2.567 GiB |         2.210 GiB |     13.9% |

Mean wall times follow. Positive percentages mean slower. Each clean mean has
three samples; each edit mean contains three sequential edits in each of three
fresh rounds, not nine independent rounds.

| Project | Build                |  Baseline |   Compact | Change | Versus matched standard |
| ------- | -------------------- | --------: | --------: | -----: | ----------------------: |
| uv      | Clean                | 143.230 s | 144.628 s |  +1.0% |                   +0.5% |
| uv      | Direct edit          |   2.562 s |   2.780 s |  +8.5% |                   +9.5% |
| uv      | Private-library edit |   6.878 s |   6.958 s |  +1.2% |                   +1.1% |
| uv      | Inline edit          |   7.591 s |   7.886 s |  +3.9% |                   +1.8% |
| Ruff    | Clean                | 124.143 s | 126.660 s |  +2.0% |                   +2.1% |
| Ruff    | Direct edit          |   1.764 s |   1.933 s |  +9.6% |                   +7.5% |
| Ruff    | Private-library edit |   2.814 s |   2.836 s |  +0.7% |                   -1.3% |
| Ruff    | Inline edit          |   2.648 s |   2.845 s |  +7.4% |                   -2.7% |

The archive design gives up some storage savings to remove the external store
and its lookup/garbage-collection requirements. The repaired external-store
control saved 32.4% on uv and 24.5% on Ruff versus matched standard; those
percentages do **not** describe the self-contained shipping interface. After
clean builds the archive saved 18.7%/13.9%, respectively; after edits its logical
byte reductions were 19.2%/14.0%.

**Decision: the storage design merits further work, but this bundle is not yet
recommended for adoption.** Clean-build overhead is modest, and the direct-edit
cost is about 0.22 seconds on uv and 0.17 seconds on Ruff. However, the ordinary
candidate already regresses the synthetic Ruff inline-helper rebuild by
**10.44%**, or **0.277 seconds**,
with compression disabled. Eight of nine paired edits were slower in both wall
and CPU time; CPU time rose by 0.227 seconds on average. All three round means
were positive (+17.74%, +13.53%, +0.51%). Therefore leaving the feature off by
default does not avoid every measured cost, and the compact arm's improvement
over matched standard on this case is not an improvement over the baseline.

The ordinary-path logs contain the same two Ruff compiler invocations and no
additional dependency rebuilds. The candidate adds archive-member probing in
`materialize_compressed_rlibs` when compact options are off; this is a plausible
contributor, not proven attribution. Resolve the ordinary-path regression with
a focused profile or A/B before adopting the bundle. Keep the Cargo option off
by default even after that issue is resolved; these two projects do not establish
a general speed or memory benefit.

Resource and round-level evidence is below. CPU changes are versus baseline;
per-round wall changes are versus matched standard. RSS is the mean of sampled
process-tree peaks, not a precise resident-memory limit. Short Ruff edit phases
are particularly sampling-sensitive; these observations do not establish a
memory improvement.

| Project | Build                | CPU time change | Sampled peak RSS, baseline → compact | Wall change by round versus standard |
| ------- | -------------------- | --------------: | -----------------------------------: | ------------------------------------ |
| uv      | Clean                |           +0.5% |                      3.32 → 3.35 GiB | -0.7%, +0.9%, +1.3%                  |
| uv      | Direct edit          |           +1.2% |                      1.21 → 1.27 GiB | +14.7%, +6.9%, +6.8%                 |
| uv      | Private-library edit |           -2.8% |                      1.24 → 1.30 GiB | +5.4%, -0.3%, -1.7%                  |
| uv      | Inline edit          |           +0.3% |                      1.25 → 1.28 GiB | +6.2%, +0.1%, -0.6%                  |
| Ruff    | Clean                |           +0.4% |                      3.85 → 3.84 GiB | +1.6%, +1.1%, +3.5%                  |
| Ruff    | Direct edit          |           +3.7% |                      0.34 → 0.66 GiB | -1.4%, +13.4%, +10.6%                |
| Ruff    | Private-library edit |           -3.3% |                      0.57 → 0.75 GiB | +4.7%, -13.2%, +7.0%                 |
| Ruff    | Inline edit          |           +2.9% |                      0.46 → 0.87 GiB | -8.5%, -1.5%, +2.3%                  |

The frozen admission rule tolerates fewer than three outside-CPU intervals per
command. There were 36 accepted single-interval flags: 35 were terminal uv
compact-arm samples consistent with the previously investigated process
reparenting issue; one interior baseline-clean spike remains unattributed.
The audit retains all flags. Small timing deltas should not be treated as proof
of a speedup, and no production PGO/BOLT performance claim is made.

The complete [compressed evidence](measurements/benchmark-receipts.tar.gz)
contains 1,284 files (524,192,690 uncompressed bytes). The archive is 31,785,165
bytes, SHA-256
`dfa3fb4f249b71d359c23e31917851f58f620393fd567b609abb33603a025c60`.
The [inventory](measurements/benchmark-inventory.json) records every member's
size and digest; the [audit program](measurements/audit-shipping.py) can check the
extracted receipts. The frozen wrapper, summarizer, and benchmark core remain
available under `harness/` and the referenced prototype harness path.

## Correctness and release integration

See [the correctness audit](audit-correctness.md) for exact-head evidence,
compatibility cases, failure diagnosis, and remaining platform coverage limits,
and the [independent safety review](safety-review.md) for checked invariants and
the fixed CI credential-authority and raw-metadata allocation findings.
The final Linux revisions passed a compiler rebuild, both forced metadata/export
suites, shared format tests, and compact-Wild/ordinary-BFD interoperability.
Earlier lifecycle, worktree, alignment, and packaging receipts retain their
separate source revisions.
The compiler distribution rehearsal checks the actual tarball's Wild binary,
capability marker, licenses, and compiler driver. It is not a production
PGO/BOLT build or a published release.

## Initial study source revisions

| Component | Measurement or earlier functional boundary                                                                               | Final review revision                      |
| --------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| Rust      | `e55e0485efc397741f4aaf861f1c74a281ac902f`                                                                               | `9546795cae23d424bec08487b4f3cace591efb5a` |
| Wild      | `dba82ebe99d98adbfe6358215d456cdddb1877da`                                                                               | `9179eb988df2676342192a24dc337cf9823e9d56` |
| Cargo     | Timing: `018a2b93409433dc5bc05c5fce838ae69e9bc396`; opt-in functional checks: `207626090e1fb9b405abd806a86c1b42bd2db5ff` | `4a2813050da607ca5cfe7b5cf3a17ba7c9676be1` |

The pristine compiler is `348339ddae4288ebb3af97d204b19479fef8f5f2`; the
shipped Wild source base is `e9a9b0cb6fd63a23cc7b93aafc931aadd5746be6` (0.10.0).
Rust CI pins Wild `9179eb988df2676342192a24dc337cf9823e9d56`. The later Rust changes cover CI, a
test-only Cargo pin update, dependency allowlists, and mechanically moved helper
and test bodies. Cargo's follow-ups change only tests. Wild's later runtime
source edits are a scoped lint annotation, removal of an unnecessary borrow, and
a raw ELF metadata length check before allocation. The latter rejects malformed input
before copying its payload and has a regression that fails before the fix and
passes afterward. Its other changes are tests, license policy, and workflows.
The final shared format crate tree is `356efe8fd992cb31b1d9163ae3c5dc0361a72814`;
the measurements retain `214c4264333a304f35506c9456828c12a9eba066`. The review
documents these boundaries. Final and measured binaries are not claimed to be identical.

The harnesses are in [harness/](harness/). The original benchmark core remains
frozen at SHA256 `ea7867f9f9a0f19ceb7d9c558aa7aa6758ae3e254878685fbc58768c65713cef`.

Compiler GitHub CI requires dedicated `OHM_SOURCE_APP_CLIENT_ID` and
`OHM_SOURCE_APP_PRIVATE_KEY` credentials in `ohm-rust`, for a read-only App
installed only on `ohm-wild`. The current checks stop at the missing client ID;
local validation is documented separately. The existing write-capable release
App key remains in its protected environment. No credentials, repository
settings, release manifests, or published defaults were changed for this study.
