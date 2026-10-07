# Cargo and release infrastructure simplification review

Review date: October 5, 2026. This is a recommendation report; no production sources were changed.

The main opportunity in Cargo is to reduce the number of independent cache protocols. Public API cutoff and shared immutable dependencies have useful evidence; incremental expiry, the scheduler replacement, and several optional experiments have much weaker cases. Remove features as complete units rather than deleting the validation that makes retained caches correct.

## Exact scope

The shipped Cargo revision is `018a2b93409433dc5bc05c5fce838ae69e9bc396`, pinned by [Ohm 1.99.0-1](https://github.com/astral-sh/ohm/blob/a7241802952abf7c827aee2099bb672875f91ed3/toolchains/1.99.0/1.json). The upstream comparison base is `5f94df4789f005f9a352888e8355ffc645b7ed0e`, Rust 1.99.0's Cargo gitlink. The base is an ancestor of the pin. The main Cargo checkout has unrelated local modifications and is on a different revision; this review uses Git objects and a temporary source snapshot.

The coordinator review uses Ohm `main` at `a7241802952abf7c827aee2099bb672875f91ed3`. Its release infrastructure has no direct upstream repository, so the relevant question is whether it introduces unnecessary divergence inside Rust bootstrap, and whether coordinator work supports a retained feature.

| Cargo comparison category | Added | Removed | Interpretation |
| --- | ---: | ---: | --- |
| Entire pinned diff | 69,114 | 1,099 | 173 paths; not all handwritten runtime complexity |
| Vendored mimalloc | 26,598 | 0 | Upstream third-party source, distinct from custom cache logic |
| Nonvendored source, build script and Cargo manifest | 13,891 | 453 | Includes inline unit tests and test-support source |
| Integration tests | 19,175 | 44 | Several cache-invalidation and concurrency matrices |
| Benchmarks and recorded evidence | 8,907 | 0 | Valuable evidence, but contributes considerably to fork size |
| Other documentation, configuration and lock changes | 543 | 602 | Remainder after the categories above |

The counts are Git line counts, not measures of risk or independent benefit. Per-commit costs are saved in [cargo-commit-costs.json](evidence/cargo-commit-costs.json). They include intermediate churn and should not be summed as a final deletion estimate.

## Recommendations

### Remove the optional incremental configuration expiry feature

[Cargo #104](https://github.com/astral-sh/ohm-cargo/pull/104) is disabled by default. Its controlled experiment assigned three configurations artificial ages of 40 days, reclaimed 221.37 MiB of 349.42 MiB of logical incremental state, and preserved 97 finished artifacts. It does not demonstrate how often configurations really become stale, physical APFS savings, or a net benefit over ordinary cleaning. The next parser edit cost 0.903 seconds after expiry versus 0.244 seconds with the state retained.

The shipped implementation adds a 617-line module, new clean CLI behavior, changes to incremental directory selection and usage tracking, marker versions, ownership checks, hourly refresh logic, profile locking, and interrupted-deletion recovery. There are 777 lines of expiry integration tests and another 283 lines of reuse tests. The initial and hardening commits add +790/-119 in nonvendored source before later interactions. See [incremental_gc.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/workspace/incremental_gc.rs).

My judgment: remove this whole feature from the shipped Cargo stack. Preserve its report and experiment branch. Rust's separate superseded-session cleanup is a different feature and should not be removed with it. If expiry returns, require observed long-running disk pressure and a policy benchmark that includes the cost of rebuilding expired data.

### Revert the dependency scheduler replacement

[Cargo #115](https://github.com/astral-sh/ohm-cargo/pull/115) replaces the upstream queue with dense indices, per-artifact counters, a binary heap, an iterative dependency walk and sparse transitive-reachability bitmaps. Its single file change is +322/-139; it adds a second representation of graph identity and changes equal-priority tie breaking.

The best recorded whole-Cargo instruction reductions are 0.27% for an unchanged Ruff check and 0.66% for an unchanged uv check. Neither invokes the compiler. Native elapsed no-op, edit and revert measurements are inconclusive and order-sensitive, and these Cargo binaries lacked release Cargo PGO. Compiler BOLT is irrelevant to these no-compiler commands. See [dependency_queue.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/util/dependency_queue.rs).

My judgment: the measured gain is too small for a wholesale replacement of upstream scheduling in this project. Revert to the upstream queue and preserve any tests that expose real upstream correctness gaps. No special benchmark is necessary to say the present evidence is insufficient; a future proposal should show a repeated representative session benefit, including concurrent builds.

### Question the separate Cargo allocator fork

[Cargo #106](https://github.com/astral-sh/ohm-cargo/pull/106) has better independent evidence than the scheduler: matched PGO builds on an Apple M5 Max improve metadata and unchanged commands by 4.6–8.3%, including Ruff check 216→199 ms and uv build 296→267 ms. Linux did not establish a win and used more memory, so Cargo uses mimalloc only on Apple Silicon.

Its custom integration is small (+37/-1 outside vendored source), but it adds another copy of mimalloc 3.5.1, a CMake dependency and a bespoke native allocator build. That is 26,598 vendored lines, additional to the compiler's allocator source. The PR explains that the chosen Rust dependency bundled the older allocator, so blindly replacing this with that dependency would change the tested implementation.

My judgment: challenge the 17–29 ms warm-command savings against the user's complexity objective. It is a consolidation or ablation candidate, not as strong a removal as the scheduler or expiry feature. Compare a real session with the system allocator using matched optimized Cargo binaries. If the gain is still confined to short no-op commands, remove the Cargo-specific allocator integration. If retained, prefer an upstream-maintained dependency when it can supply the tested implementation rather than maintaining duplicate native sources. Do not delete license or provenance records just to reduce line counts.

### Keep resolver reuse, but retain a narrow contract

[Cargo #66](https://github.com/astral-sh/ohm-cargo/pull/66) is +279/-11 source initially, with execution-setting-key refinement [#88](https://github.com/astral-sh/ohm-cargo/pull/88) adding +61/-1. The final dedicated cache file is 237 lines. It fingerprints all relevant manifests, the lockfile, Cargo/compiler identity, resolver modes, configuration and relevant environment, stores an atomic digest, and reuses the earlier complete workspace resolution. It still resolves selected package features.

The historical original [#16](https://github.com/astral-sh/ohm-cargo/pull/16) reports graph reuse alone reducing warmed Codex metadata 413→358 ms and Nextest 961→824 ms, with actual dependency-edit check/Clippy/Nextest reductions of 125/218/246 ms. These measurements predate the current compiler/Cargo base; they are evidence for the feature, not current-head estimates.

My judgment: provisionally keep this relatively bounded optimization. Unlike parsed-lockfile caching, it avoids more than TOML decoding and has useful workflow evidence. Rebenchmark on current sources before broadening its scope. Do not turn it into a daemon, persisted executable plan or second lockfile representation. The manifest fingerprint is already recomputed across invocations, so it should be evaluated as part of total Cargo startup cost, not merely cache-hit lookup latency. See [resolve_cache.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/ops/resolve_cache.rs).

### Simplify shared-cache provenance by sharing facts, not weakening policies

Shared registry caching and build-to-check reuse own a substantial part of the Cargo fork. The initial implementations add +2,267/-40 and +1,285/-13 nonvendored source respectively. Active-graph eligibility adds +1,223/-102. Procedural macro and native-tool policies, compiler provenance and cache admission add further hundreds of lines. The final changed files include +2,390/-7 in `compilation_files.rs`, +1,356/-11 in `build_runner/mod.rs`, +1,290/-2 in `unit_dependencies.rs` and +1,980/-107 in fingerprints; these totals also include other features.

The user-visible evidence is materially stronger than for many micro-optimizations: the latest complete release's build-then-check examples save roughly 46.56 seconds for uv and 61.86 seconds for Codex, and cross-worktree registry reuse saves seconds. Those examples combine multiple mechanisms; they do not isolate every extension to eligibility.

There are multiple compiler-driver identity implementations and related executable, loader, codegen-backend, environment and toolchain checks across:

- [compilation_files.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/compiler/build_runner/compilation_files.rs)
- [build_runner/mod.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/compiler/build_runner/mod.rs)
- [unit_dependencies.rs](https://github.com/astral-sh/ohm-cargo/blob/018a2b93409433dc5bc05c5fce838ae69e9bc396/src/compiler/unit_dependencies.rs)

My judgment: keep the basic shared cache and build-to-check reuse, and consolidate common low-level facts into one bounded provenance implementation. Keep separate decisions about registry sharing, cross-mode reuse and seed eligibility, because their contracts differ. This is a focused refactor candidate, not a reason to introduce an all-purpose cache framework. A second simplification option is to reduce the set of admitted macro/native-tool cases and let excluded cases use ordinary Cargo behavior; measure loss of actual cache hit coverage before choosing it.

Do not remove deadlock repairs, exact bundled-Wild recognition, compiler identity checks, lock lifetimes, diagnostic replay, native-input boundaries or fingerprint validation independently. They support correctness of retained optimizations.

### Keep the clone-only worktree design, with a higher bar for further admission features

[Cargo #101](https://github.com/astral-sh/ohm-cargo/pull/101) introduces source checksum relocation, import staging, build-script reruns and output verification, private snapshots and a Git worktree CLI. Its initial source change is +1,479/-30. The final main worktree module is 628 lines and script-result revalidation is 272 lines; source and fingerprint hooks live elsewhere.

The original controlled local macOS comparison, with warm registry artifacts and permissive macro/native trust, measured worktree creation plus first build 23.95→3.59 seconds unchanged and 25.08→8.33 seconds with an edit. The latest release's APFS disk figures have sizable bundled savings across worktrees. This is a meaningful Ohm use case, although the controlled timing only has two samples per arm and includes the compiler relocation change.

[Cargo #126](https://github.com/astral-sh/ohm-cargo/pull/126) simplifies import policy by requiring copy-on-write cloning and eliminating the byte-copy fallback and override. Keep that policy: earlier byte-copying measurements added 15 seconds for Ruff forks and 44–59 seconds for uv. Ordinary I/O errors still need to surface; unsupported cloning is a seed miss. The independently checked clone probe is part of ensuring the feature really works, not removable test-only machinery.

[Cargo #108](https://github.com/astral-sh/ohm-cargo/pull/108) isolates bundled Clippy state so subsequent worktrees can retain build/test seeds. Its APFS workflow shows 27.044→23.595 seconds and 984.916→859.350 MiB of final allocation, with four samples per arm. Repeated donor Clippy costs about 14.95 ms more, or 16.66%, and three of four pairs are slower. This supports keeping the feature for the measured worktree workflow, while explicitly accepting a short-command cost. It is not evidence for a Linux byte-copy speedup.

My judgment: keep worktree seeds and Clippy isolation together as a coherent feature. Stop adding separate import modes. Local-macro trust [#103](https://github.com/astral-sh/ohm-cargo/pull/103) deserves separate scrutiny: it lowers APFS allocation and compiler invocations in a local pilot, but does not establish general elapsed benefit and expands the correctness contract. The supplied global instructions explicitly select macro/native-tool trust and worktree seeding, so this review treats that as an intentional workflow, rather than assuming the policy is unused. Keep it provisionally and measure its marginal value. If it is removed, remove its entire policy surface; do not weaken validation of remaining imports.

## Complete shipped Cargo family inventory

Every commit in the release comparison was classified. Costs below are initial or selected source commits, excluding mimalloc vendor material; overlapping modifications and later repairs mean these are not additive final savings.

| Family and PRs | Cost or evidence | Recommendation |
| --- | --- | --- |
| Public API transport/cutoff and generations #53, #52, #55 | Initial +1,231/-105, +145/-15, +11/-3 source; substantial compiler counterpart | Keep the core; independently demonstrated large private dependency edit win |
| Cached relinking #51, #65, #67, #70 | +602/-2 initial; #65 reduces source -21 net by doing link-state emission in one invocation | Keep as a core companion to cutoff; keep objects out of search paths and avoid save-temps |
| Ohm defaults #54, #90 | +151/-25 initial; frontend enable itself +2/-1 | Keep a single defaults policy; no new default without marginal evidence |
| Already upstream at Rust 1.99 #56–60, #62–64 | Eight exact empty implementation commits | Drop them from next stack replay and release feature claims |
| Remote manifest backport #61 | +49/-9 source remains | Retain only until upstream base includes it; bounded backport |
| Metadata dedup #68 | +48/-2 source, with embedded-metadata exclusions | Keep pending broader storage assessment; low custom cost relative to cache features |
| Terminal/immutable public-hash skips #69, #84, #87 | +77/-31, +24/-4, +31/-2 | Keep as scoped avoidance of core-feature overhead; don't remove the consumer hash checks |
| Metadata-ready pipeline #71 | +118/-8 source, +675/-17 whole commit | Keep dependency scheduling that repairs cutoff's unnecessary serialization |
| Unused integration dependency handling #72, #73 | +357/-35 and +261/-13 source; historical test wins 8.26→5.14 s and 7.20→4.41 s | Keep provisionally; measure current broad sessions; preserve native/transitive link checks |
| Focused test compilation #74 | +39 Cargo source, +327/-25 total, substantial compiler support | Remove/defer with compiler feature unless current use demonstrates enough benefit; disabled-by-default behavior surface |
| Workspace codegen/test defaults #76, #93, related output invalidation | +91/-2 and +38 source plus compiler machinery | Judge with compiler partition reuse, not as independent tiny Cargo changes |
| Registry build-to-check and mixed graph reuse #75, #78, #85 | +1,285/-13, +1,223/-102, +111/-20 source | Keep core; consolidate validation and resist further eligibility modes |
| Shared registry artifacts #77 | +2,267/-40 initial source | Keep provisionally; high-value multi-worktree workflow |
| Macro/native trust and mirrors #79, #82, #99 | +318/-63, +321/-75, +167/-63 source | Simplify common admission facts; benchmark marginal eligible-hit coverage; retain checksums and source identity |
| Locked package name index #80 | +21/-1 source | Low-cost scaling fix; retain or upstream, not a priority removal |
| Driver validation dedup #81 | +16/-12 source | Retain as local simplification of an expensive retained feature |
| Early cutoff/shared cache compatibility #83 | +130/-25 source | Required repair if both retained |
| File descriptor budget #86 | +178 source, includes unit tests | Required for per-unit locks; do not remove it alone |
| Resolver cache #66, #88 | Final dedicated module 237 lines, historical tens/hundreds of ms saved | Keep bounded; current-base ablation desirable |
| Established check graphs and workspace reuse #89, #91 | +282/-24 and +117/-39 source | Keep provisionally with cross-mode reuse; avoid expansion into test-feature supersets |
| Skipped compiler invocation repair #94 | +3/-4 source | Keep tiny correctness repair |
| Concurrent miss coalescing #96 | +149/-13 source; only dependency-free pure libraries eligible | Question marginal value; broaden only with real contention evidence; safety checks must remain if retained |
| Shared locking/deadlock/nested execution #100 | Three source commits +970/-157; no-op overhead reported 20–24 ms | Required repair of retained shared cache; architecture can be simplified only as a unit |
| Worktree seeding/defaults #101 | Final 628-line main module plus revalidation/fingerprint hooks | Keep clone-only feature; meaningful controlled macOS win |
| Trusted local macro import #103 | +75/-17 source | Question opt-in surface; requires deliberate use, not just smaller pilot disk allocation |
| Source checksum buffer #105 | +14/-7 source; full command -1.67% to +0.87% mixed | Tiny local simplification; not a high-cost candidate despite no whole-command win |
| Cargo mimalloc #106 | +37/-1 custom integration, 26,598 vendored lines | Challenge small absolute gains; consolidate or ablate |
| Incremental expiry #104 | 617-line module, over 1,000 integration test lines and large evidence corpus | Remove from shipping stack |
| Clippy seed isolation #108 | Two implementation commits +535/-219 source, plus substantial evidence/CI | Keep for clone-capable worktree workflow, accept/retest donor no-op overhead |
| Bundled upstream Wild #114, cache fix #123 | Final 148-line selection module; cache compatibility +70/-4 | Keep upstream linker option, require current session attribution before expanding it |
| Indexed scheduler #115 | +322/-139 one-file replacement; 0.27–0.66% instructions only | Revert |
| Clone-only seeds #126 | +279/-113 source across policy/probe commits | Keep simplification and required fallback checks |
| Line-table defaults #127 | +18/-5 source, documentation and tests | Keep if intended debugger tradeoff is accepted; large bundled claims must account for this changed profile |
| CI, README, help and regression fixtures | No separate runtime benefit expected | Keep necessary fork operations; delete obsolete feature-specific fixtures only with feature removal |

## Unshipped Cargo experiments

These should not be confused with source in the pinned release. Open PR state also does not mean unshipped: the release is made from a stack of open PR heads.

| Experiment | Evidence and complexity | Recommendation |
| --- | --- | --- |
| Parsed lockfile cache #97 | Metadata 273→271 ms; warm check 49.7→49.4 ms, 30 alternating samples; closed/excluded | Leave excluded; do not revive |
| Immutable generations #98 | Demonstrates lock-free readers but no general speedup; retains old generations without reclamation; closed/excluded | Leave excluded; adds a second publication/reclamation protocol |
| Test-unified dev graph #50 | One 7.48 vs 76.45 s warm measurement, but extra dev features can mask ordinary-check errors; closed/excluded | Leave excluded; behavioral compromise and narrow nonrepeated evidence |
| Cargo sessions and persistent workers #107, #110–113, #116–117 | Historical timing packets refer to removed watcher/freshness layers; workspace/daemon/compiler lifecycle and invalidation complexity | Archive as research unless one consolidated integration has current end-to-end evidence; not in shipped pin |
| Combined Clippy/codegen #102 | Excluded from release; compiler/tool counterpart required | Leave excluded; see tools review |
| Metadata omission for internal workspace libs #109 | Excluded experiment; alters artifact interoperability | Leave excluded pending meaningful full-workflow space benefit |
| Alternative Clippy/prefix/cloning PRs #118–120 | Superseded/consolidated; prefix cloning excluded | Keep only the single shipped isolation/clone-only policy, not alternatives |
| LTO generic sharing #132 | uv builds improve 18.51–24.94%; Ruff fat-LTO fresh builds regress 3.5%, entry edits ~5.8%, bounded runtime regressions | Hold as workload-specific research; not local-dev default; no claim of global simplification win |
| Early interface checks #133 | Three pairs: Ruff workspace rebuild ~20.6%, rust-analyzer ~26.1%; private parser edit essentially unchanged | Promising but hold outside minimal stack until compiler/Cargo protocol is mature; separate rebuild use case |
| Compact artifacts #134 | Coordinator #140: 19.0% uv/13.9% Ruff allocated-storage savings; clean cost 1–2%, direct edit ~0.22/0.17 s; Ruff inline regression even disabled | Hold bundle; introduces compiler/Cargo/Wild format coupling and costs outside the enabled mode |

## Coordinator and release infrastructure

The coordinator has about 11,851 lines across the inspected scripts, tests, workflows and docs. More than 4,000 lines are benchmark/session test modules; this is research and release infrastructure rather than runtime upstream divergence. The coordinator necessarily needs immutable source pins, matching component identities, installer checksums, source verification, publishing and installed-toolchain smoke tests.

### Keep upstream release optimization, question custom component training

The release uses upstream Rust `opt-dist` for compiler PGO and Linux BOLT, matching CI LLVM and official compiler settings. Retain that foundation. Comparing an unoptimized custom compiler to stock Rust would hide algorithmic benefit under packaging regressions.

The extra component-PGO stack [Rust #67](https://github.com/astral-sh/ohm-rust/pull/67) explicitly states that Ohm-specific gains have not been measured. Upstream Rust 1.99 already actively instruments, trains and uses Cargo and rustdoc PGO. Ohm adds Clippy and rustfmt/cargo-fmt training, separates rustdoc's profile directory, and selects the rustdoc driver explicitly. The current net `opt-dist` production differences include environment +34, exec +77/-37, main +65/-24 and training +193/-4, with separate tests and bootstrap propagation. This includes other additions such as Wasm target preparation; a revert must select the component-training subset rather than discard whole files. The coordinator also verifies each merged profile's actual covered symbols.

My judgment: benchmark the incremental contribution of Clippy and formatter PGO and the changed rustdoc training contract over upstream's existing compiler/Cargo/rustdoc optimization. If no material session gain appears, remove only the additional training and bootstrap knobs while preserving upstream optimization. This is a strong candidate because the current PR supplies no marginal benefit evidence. Do not remove active upstream Cargo/rustdoc PGO or count its machinery as fork complexity.

Historical [Ohm #61](https://github.com/astral-sh/ohm/pull/61) trained supplementary Ruff/uv/Codex workflows. That supplementary custom corpus is absent from the inspected current `opt-dist` source; it is not a current removal candidate.

### Keep release repairs and identity validation

The LLVM 23 native PGO/ThinLTO and BOLT updates ([Ohm #134](https://github.com/astral-sh/ohm/pull/134), [#136](https://github.com/astral-sh/ohm/pull/136), [#137](https://github.com/astral-sh/ohm/pull/137)) repair concrete crashes or incompatible formats. They are required for retained optimization, not speculative performance features. Similarly, installed smoke tests have detected actual Wild/shared-cache interaction failures. Keep those tests and exact source/compiler/component verification.

Wasm std, rust-src and the rust-analyzer proc-macro server are distribution capabilities, not compiler-speed optimizations. They add bounded packaging support needed because Rustup cannot add ordinary targets/components to a custom linked toolchain. Retain if these are supported user workflows; do not assess them against an isolated build-time speedup requirement.

### Remove infrastructure with abandoned experiments

The [resident compiler experiment harness](https://github.com/astral-sh/ohm/pull/127), [release optimization studies](https://github.com/astral-sh/ohm/pull/139) and [compact artifact coordinator](https://github.com/astral-sh/ohm/pull/140) should remain separate from the shipping/release path while held. When a feature is archived, keep its final evidence packet rather than active CI matrices, capability checks and repeated release-list entries.

There are compatibility branches for old immutable sources in release tooling. Their purpose is historical reproducibility. A lean current-release builder could drop old-source support only if archived releases remain reproducible via their corresponding coordinator commit; changing that policy is separate from deleting current safety checks. This is a lower-priority operational simplification, not evidence of runtime waste.

## Removal and validation order

1. Restore purely incidental upstream formatting and stop replaying empty backports. No runtime benchmark needed.
2. Remove Cargo expiry as a whole, including its CLI, flags, directory-selection/tracking hooks, legacy-marker tests and feature-specific CI. Verify ordinary Cargo clean and existing worktree/shared-cache tests still pass.
3. Restore upstream scheduling, then compare no-op, edited and concurrent builds against the same remaining stack. Keep artifact-specific readiness and upstream behavior.
4. Remove compiler/tool micro-features with weak marginal evidence in separate reviewable changes; then run one aggregate lean-stack session comparison rather than rebenchmark every seven-line change independently.
5. Consolidate provenance facts only after dead branches are gone. Retain all behavior-focused rejection/rebuild tests needed by the remaining caches.
6. Compare component PGO and Cargo allocator with matched optimized binaries. Neither existing bundled benchmark tables nor a plain local debug Cargo build answer these questions.
7. Preserve the upstream-Wild option and clone-only seeds; do not package Wild-fork, Mach-O, resident-query or compact-format experiments as part of this simplification.

No change above was applied during this review. The recommendations distinguish measured improvement, missing evidence, deliberate capability tradeoffs and my maintenance-cost judgment.
