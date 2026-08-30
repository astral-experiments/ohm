# Changes from upstream

Ohm 1.98.0-4 caches diagnostics from audited Clippy passes across edits, fixes shared registry cache deadlocks between concurrent worktrees, and reduces allocations when checking well-formedness obligations. Its source repositories use the exact upstream Rust 1.98.0 release sources, and changes are listed from each fork-specific CI foundation through the selected pull-request stacks.

Clippy runs 56 audited late passes covering 62 lint kinds through incremental module queries. Unchanged modules can replay their diagnostics without rerunning those passes. Compiler-driver inputs participate in cache compatibility, and source-sensitive suggestions track the files they read, including comment and macro-context changes. Other passes retain their existing traversal; compilers without the required hooks also retain the existing path.

Module lint queries now observe individual effective-visibility entries instead of the entire map. Adding an unrelated exported item no longer invalidates every module through that dependency, while changes to a relevant item's visibility still update its diagnostics. Whole-crate passes and nonincremental builds retain direct map lookups.

Cargo reserves shared registry unit locks in a consistent order, retaining read locks for fresh units and write locks for dirty units. This repairs deadlocks between simultaneous cold worktrees and keeps the locks alive for scheduled compiler, build-script, and rustdoc children on Linux and macOS. Nested builds fall back to private artifacts. The shared-cache namespace changes, so the first build repopulates affected artifacts; this is a correctness repair, and lock preparation can add overhead to unchanged builds.

Well-formedness checking collects ancestor predicate slices once and instantiates them directly into the final obligations, preserving substitution, diagnostic spans, ordering, and escaping-bound-variable filtering. The compiler's Cargo gitlink selects the exact Cargo revision in the release manifest. The existing component profile-guided optimization, parallel compiler frontend, dependency reuse, and formatter optimizations remain enabled.

The optional parsed-lockfile cache remains disabled by default and is available through `CARGO_EXPERIMENTAL_LOCKFILE_PARSE_CACHE=1`. The parallel query-cache promotion experiment is stacked above the selected compiler revision and remains excluded until its independent release performance benefit is established.

Published Rust 1.97.1 and Ohm 1.98.0-1, 1.98.0-2, and 1.98.0-3 benchmark measurements, historical failure disclosures, replay artifacts, and recorded source fixtures remain unchanged. They are historical results and are not represented as measurements of this release.

## ohm-rust

- [#6: Set up fork-owned Rust CI](https://github.com/astral-sh/ohm-rust/pull/6)
- [#36: Run compiler regression tests on Namespace macOS runners](https://github.com/astral-sh/ohm-rust/pull/36)
- [#43: Add reachability-based public API hashing](https://github.com/astral-sh/ohm-rust/pull/43)
- [#44: Skip query machinery when promoting disk-cached values](https://github.com/astral-sh/ohm-rust/pull/44)
- [#45: Emit reusable link state while linking normally](https://github.com/astral-sh/ohm-rust/pull/45)
- [#46: Skip codegen objects when indexing crate search paths](https://github.com/astral-sh/ohm-rust/pull/46)
- [#47: Preserve reusable link objects without saving all compiler temporaries](https://github.com/astral-sh/ohm-rust/pull/47)
- [#48: Index loaded crates by name and public API hash](https://github.com/astral-sh/ohm-rust/pull/48)
- [#49: Skip irrelevant foreign specialization impls](https://github.com/astral-sh/ohm-rust/pull/49)
- [#50: Cache successful privacy walks within each module](https://github.com/astral-sh/ohm-rust/pull/50)
- [#51: Avoid allocating when compiler strings need no escaping](https://github.com/astral-sh/ohm-rust/pull/51)
- [#52: Prune unreachable metadata before public API hashing](https://github.com/astral-sh/ohm-rust/pull/52)
- [#53: Restore generic sharing under public API hashing](https://github.com/astral-sh/ohm-rust/pull/53)
- [#54: Reuse monomorphization partitions across incremental builds](https://github.com/astral-sh/ohm-rust/pull/54)
- [#55: Skip unnecessary integration-test relinking](https://github.com/astral-sh/ohm-rust/pull/55)
- [#56: Reuse monomorphization partitions after library closure edits](https://github.com/astral-sh/ohm-rust/pull/56)
- [#57: Reuse metadata prefixes across incremental builds](https://github.com/astral-sh/ohm-rust/pull/57)
- [#58: Add explicit focused test-harness compilation](https://github.com/astral-sh/ohm-rust/pull/58)
- [#59: Partition upstream generics by their local callers](https://github.com/astral-sh/ohm-rust/pull/59)
- [#60: Keep incremental codegen-unit merges stable across edits](https://github.com/astral-sh/ohm-rust/pull/60)
- [#61: Format only changed Cargo workspace packages](https://github.com/astral-sh/ohm-rust/pull/61)
- [#62: Preserve recursion limits during parallel query evaluation](https://github.com/astral-sh/ohm-rust/pull/62)
- [#63: Pin the Rust 1.98 Ohm Cargo stack](https://github.com/astral-sh/ohm-rust/pull/63)
- [#67: Profile-optimize Cargo, rustdoc, Clippy, and rustfmt](https://github.com/astral-sh/ohm-rust/pull/67)
- [#65: Reuse monomorphization partitions in incremental test builds](https://github.com/astral-sh/ohm-rust/pull/65)
- [#69: Pin Cargo test defaults and skipped-wrapper repair](https://github.com/astral-sh/ohm-rust/pull/69)
- [#70: Pin Cargo for Ohm 1.98.0-3](https://github.com/astral-sh/ohm-rust/pull/70)
- [#71: Track external driver inputs in incremental cache compatibility](https://github.com/astral-sh/ohm-rust/pull/71)
- [#73: Track source files as incremental query inputs](https://github.com/astral-sh/ohm-rust/pull/73)
- [#74: Track individual visibility inputs for module lints](https://github.com/astral-sh/ohm-rust/pull/74)
- [#72: Stream well-formedness obligations](https://github.com/astral-sh/ohm-rust/pull/72)
- [#75: Pin Cargo for Ohm 1.98.0-4](https://github.com/astral-sh/ohm-rust/pull/75)

## ohm-cargo

- [#7: Set up fork-owned Cargo CI](https://github.com/astral-sh/ohm-cargo/pull/7)
- [#43: Use Namespace runners for macOS CI](https://github.com/astral-sh/ohm-cargo/pull/43)
- [#53: Prototype reduced dependency rebuilds with public API hashes](https://github.com/astral-sh/ohm-cargo/pull/53)
- [#52: Preserve semantic metadata and transitive link generations](https://github.com/astral-sh/ohm-cargo/pull/52)
- [#51: Prototype cached relinking for dependency-only rebuilds](https://github.com/astral-sh/ohm-cargo/pull/51)
- [#55: Enable RDR early cutoff for check and Clippy](https://github.com/astral-sh/ohm-cargo/pull/55)
- [#54: Enable Ohm build defaults](https://github.com/astral-sh/ohm-cargo/pull/54)
- [#56: Avoid cloning manifests when preparing diagnostics](https://github.com/astral-sh/ohm-cargo/pull/56)
- [#57: Avoid cloning parsed TOML manifests](https://github.com/astral-sh/ohm-cargo/pull/57)
- [#58: Use FxHash collections throughout Cargo](https://github.com/astral-sh/ohm-cargo/pull/58)
- [#59: Index workspace members for faster discovery](https://github.com/astral-sh/ohm-cargo/pull/59)
- [#60: Avoid parsing unchanged lockfiles](https://github.com/astral-sh/ohm-cargo/pull/60)
- [#62: Initialize Git HTTP transports only when needed](https://github.com/astral-sh/ohm-cargo/pull/62)
- [#61: Deserialize remote manifests without retaining TOML documents](https://github.com/astral-sh/ohm-cargo/pull/61)
- [#63: Avoid cloning registry index summaries](https://github.com/astral-sh/ohm-cargo/pull/63)
- [#64: Preallocate registry and target vectors](https://github.com/astral-sh/ohm-cargo/pull/64)
- [#65: Initialize cached relinking in one compiler invocation](https://github.com/astral-sh/ohm-cargo/pull/65)
- [#66: Cache workspace resolution across Cargo invocations](https://github.com/astral-sh/ohm-cargo/pull/66)
- [#67: Keep cached relink objects out of dependency search paths](https://github.com/astral-sh/ohm-cargo/pull/67)
- [#68: Avoid embedding crate metadata in Ohm library artifacts](https://github.com/astral-sh/ohm-cargo/pull/68)
- [#70: Avoid saving unnecessary temporaries for cached relinking](https://github.com/astral-sh/ohm-cargo/pull/70)
- [#69: Skip public API hashing for terminal check targets](https://github.com/astral-sh/ohm-cargo/pull/69)
- [#71: Pipeline early-cutoff dependencies when public APIs change](https://github.com/astral-sh/ohm-cargo/pull/71)
- [#72: Skip relinking integration tests with unused package libraries](https://github.com/astral-sh/ohm-cargo/pull/72)
- [#73: Reuse integration executables across unused dependency changes](https://github.com/astral-sh/ohm-cargo/pull/73)
- [#74: Add opt-in focused test compilation](https://github.com/astral-sh/ohm-cargo/pull/74)
- [#76: Enable incremental codegen optimizations for workspace builds](https://github.com/astral-sh/ohm-cargo/pull/76)
- [#75: Reuse built registry dependencies during checks](https://github.com/astral-sh/ohm-cargo/pull/75)
- [#77: Share immutable registry artifacts across worktrees](https://github.com/astral-sh/ohm-cargo/pull/77)
- [#78: Expand registry reuse across active dependency graphs](https://github.com/astral-sh/ohm-cargo/pull/78)
- [#80: Index locked packages by dependency name](https://github.com/astral-sh/ohm-cargo/pull/80)
- [#81: Deduplicate compiler-driver validation for reused dependencies](https://github.com/astral-sh/ohm-cargo/pull/81)
- [#79: Share audited procedural macros across worktrees](https://github.com/astral-sh/ohm-cargo/pull/79)
- [#82: Scope opaque native tools to affected registry dependencies](https://github.com/astral-sh/ohm-cargo/pull/82)
- [#83: Restore early cutoff with shared registry caching](https://github.com/astral-sh/ohm-cargo/pull/83)
- [#84: Skip public API hashing for terminal test harnesses](https://github.com/astral-sh/ohm-cargo/pull/84)
- [#85: Preserve compatible registry reuse across mixed test graphs](https://github.com/astral-sh/ohm-cargo/pull/85)
- [#86: Scale file descriptor budgets for fine-grained build locks](https://github.com/astral-sh/ohm-cargo/pull/86)
- [#87: Skip public API hashing for immutable registry libraries](https://github.com/astral-sh/ohm-cargo/pull/87)
- [#88: Avoid resolver cache misses for execution-only settings](https://github.com/astral-sh/ohm-cargo/pull/88)
- [#89: Preserve established check graphs after test builds](https://github.com/astral-sh/ohm-cargo/pull/89)
- [#90: Enable the parallel frontend in Ohm defaults](https://github.com/astral-sh/ohm-cargo/pull/90)
- [#91: Reuse built workspace dependencies during checks](https://github.com/astral-sh/ohm-cargo/pull/91)
- [#93: Enable test-binary monomorphization reuse in Ohm defaults](https://github.com/astral-sh/ohm-cargo/pull/93)
- [#94: Handle skipped compiler invocations in relink-only builds](https://github.com/astral-sh/ohm-cargo/pull/94)
- [#99: Trust authenticated crates.io packages from registry mirrors](https://github.com/astral-sh/ohm-cargo/pull/99)
- [#96: Coalesce concurrent misses for shared registry libraries](https://github.com/astral-sh/ohm-cargo/pull/96)
- [#97: Experiment with caching parsed lockfiles](https://github.com/astral-sh/ohm-cargo/pull/97)
- [#100: Fix shared registry cache deadlocks](https://github.com/astral-sh/ohm-cargo/pull/100)

## ohm-rust-clippy

- [#31: Set up fork-owned Clippy CI](https://github.com/astral-sh/ohm-rust-clippy/pull/31)
- [#35: Run Clippy tests on Namespace macOS runners](https://github.com/astral-sh/ohm-rust-clippy/pull/35)
- [#38: Skip redundant-clone analysis for clone-free functions](https://github.com/astral-sh/ohm-rust-clippy/pull/38)
- [#37: Backport allocation-free documentation tab scanning](https://github.com/astral-sh/ohm-rust-clippy/pull/37)
- [#36: Backport ASCII fast path for Unicode lint scans](https://github.com/astral-sh/ohm-rust-clippy/pull/36)
- [#39: Backport unnecessary_mut_passed query deferral](https://github.com/astral-sh/ohm-rust-clippy/pull/39)
- [#40: Backport empty disallowed-methods guard](https://github.com/astral-sh/ohm-rust-clippy/pull/40)
- [#41: Port used-underscore name prefilters](https://github.com/astral-sh/ohm-rust-clippy/pull/41)
- [#42: Backport test-item crate prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/42)
- [#43: Backport delayed external-macro checks](https://github.com/astral-sh/ohm-rust-clippy/pull/43)
- [#44: Skip nonstandard-macro analysis when the lint is disabled](https://github.com/astral-sh/ohm-rust-clippy/pull/44)
- [#45: Backport deferred MSRV checks](https://github.com/astral-sh/ohm-rust-clippy/pull/45)
- [#46: Experiment with empty-attribute MSRV parsing fast path](https://github.com/astral-sh/ohm-rust-clippy/pull/46)
- [#48: Cache audited Clippy late passes per module](https://github.com/astral-sh/ohm-rust-clippy/pull/48)
- [#49: Cache source-sensitive Clippy passes per module](https://github.com/astral-sh/ohm-rust-clippy/pull/49)

## ohm-rustfmt

- [#1: Set up fork-owned rustfmt CI](https://github.com/astral-sh/ohm-rustfmt/pull/1)
- [#12: Use Namespace macOS runners for rustfmt CI](https://github.com/astral-sh/ohm-rustfmt/pull/12)
- [#13: Format only changed Cargo workspace packages](https://github.com/astral-sh/ohm-rustfmt/pull/13)
- [#14: Format only changed Cargo workspace modules](https://github.com/astral-sh/ohm-rustfmt/pull/14)
- [#15: Avoid reverifying clean formatter checks](https://github.com/astral-sh/ohm-rustfmt/pull/15)
- [#16: Share clean formatter caches between format and check](https://github.com/astral-sh/ohm-rustfmt/pull/16)
- [#17: Avoid redundant formatter configuration ancestor walks](https://github.com/astral-sh/ohm-rustfmt/pull/17)
- [#18: Reuse unchanged formatter configuration snapshots](https://github.com/astral-sh/ohm-rustfmt/pull/18)
- [#19: Batch independently certified formatter leaf modules](https://github.com/astral-sh/ohm-rustfmt/pull/19)
- [#20: Avoid unnecessary formatter module topology discovery](https://github.com/astral-sh/ohm-rustfmt/pull/20)
- [#21: Avoid reverifying formatter runs that rewrite no files](https://github.com/astral-sh/ohm-rustfmt/pull/21)
