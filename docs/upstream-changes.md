# Changes from upstream

The Ohm source repositories are based on Rust 1.97.1. Pull requests are listed from the base of each
repository's stack to its tip, including the fork-specific CI foundation.

This is a point-in-time inventory. The linked pull requests and pinned release manifest remain the
sources of truth for the current changes and release revisions.

## ohm-rust

- [#6: Set up fork-owned Rust CI](https://github.com/astral-sh/ohm-rust/pull/6)
- [#1: Add reachability-based public API hashing](https://github.com/astral-sh/ohm-rust/pull/1)
- [#2: Pin Ohm Cargo for Rust 1.97.1](https://github.com/astral-sh/ohm-rust/pull/2)
- [#4: Pin Ohm Cargo check cutoff](https://github.com/astral-sh/ohm-rust/pull/4)
- [#5: Pin Cargo with Ohm build defaults](https://github.com/astral-sh/ohm-rust/pull/5)
- [#9: Skip query machinery when promoting disk-cached values](https://github.com/astral-sh/ohm-rust/pull/9)
- [#8: Emit reusable link state while linking normally](https://github.com/astral-sh/ohm-rust/pull/8)
- [#10: Skip codegen objects when indexing crate search paths](https://github.com/astral-sh/ohm-rust/pull/10)
- [#11: Reuse green-marking edges during incremental query promotion](https://github.com/astral-sh/ohm-rust/pull/11)
- [#12: Preserve reusable link objects without saving all compiler temporaries](https://github.com/astral-sh/ohm-rust/pull/12)
- [#13: Index loaded crates by name and public API hash](https://github.com/astral-sh/ohm-rust/pull/13)
- [#14: Skip irrelevant foreign specialization impls](https://github.com/astral-sh/ohm-rust/pull/14)
- [#15: Cache successful privacy walks within each module](https://github.com/astral-sh/ohm-rust/pull/15)
- [#16: Avoid allocating when compiler strings need no escaping](https://github.com/astral-sh/ohm-rust/pull/16)
- [#17: Prune unreachable metadata before public API hashing](https://github.com/astral-sh/ohm-rust/pull/17)
- [#18: Pin Cargo with terminal public API hash optimization](https://github.com/astral-sh/ohm-rust/pull/18)
- [#19: Restore generic sharing under public API hashing](https://github.com/astral-sh/ohm-rust/pull/19)
- [#20: Pin Cargo with conditional metadata pipelining](https://github.com/astral-sh/ohm-rust/pull/20)
- [#22: Reuse monomorphization partitions across incremental builds](https://github.com/astral-sh/ohm-rust/pull/22)
- [#21: Skip unnecessary integration-test relinking](https://github.com/astral-sh/ohm-rust/pull/21)
- [#23: Reuse monomorphization partitions after library closure edits](https://github.com/astral-sh/ohm-rust/pull/23)
- [#24: Reuse metadata prefixes across incremental builds](https://github.com/astral-sh/ohm-rust/pull/24)
- [#26: Pin Cargo with unused integration dependency reuse](https://github.com/astral-sh/ohm-rust/pull/26)
- [#25: Add explicit focused test-harness compilation](https://github.com/astral-sh/ohm-rust/pull/25)

## ohm-cargo

- [#7: Set up fork-owned Cargo CI](https://github.com/astral-sh/ohm-cargo/pull/7)
- [#1: Prototype reduced dependency rebuilds with public API hashes](https://github.com/astral-sh/ohm-cargo/pull/1)
- [#6: Preserve semantic metadata and transitive link generations](https://github.com/astral-sh/ohm-cargo/pull/6)
- [#2: Prototype cached relinking for dependency-only rebuilds](https://github.com/astral-sh/ohm-cargo/pull/2)
- [#4: Enable RDR early cutoff for check and Clippy](https://github.com/astral-sh/ohm-cargo/pull/4)
- [#5: Enable Ohm build defaults](https://github.com/astral-sh/ohm-cargo/pull/5)
- [#9: Avoid cloning manifests when preparing diagnostics](https://github.com/astral-sh/ohm-cargo/pull/9)
- [#10: Avoid cloning parsed TOML manifests](https://github.com/astral-sh/ohm-cargo/pull/10)
- [#11: Use FxHash collections throughout Cargo](https://github.com/astral-sh/ohm-cargo/pull/11)
- [#12: Index workspace members for faster discovery](https://github.com/astral-sh/ohm-cargo/pull/12)
- [#13: Avoid parsing unchanged lockfiles](https://github.com/astral-sh/ohm-cargo/pull/13)
- [#14: Initialize Git HTTP transports only when needed](https://github.com/astral-sh/ohm-cargo/pull/14)
- [#15: Deserialize remote manifests without retaining TOML documents](https://github.com/astral-sh/ohm-cargo/pull/15)
- [#19: Avoid cloning registry index summaries](https://github.com/astral-sh/ohm-cargo/pull/19)
- [#20: Preallocate registry and target vectors](https://github.com/astral-sh/ohm-cargo/pull/20)
- [#18: Initialize cached relinking in one compiler invocation](https://github.com/astral-sh/ohm-cargo/pull/18)
- [#16: Cache workspace resolution across Cargo invocations](https://github.com/astral-sh/ohm-cargo/pull/16)
- [#21: Keep cached relink objects out of dependency search paths](https://github.com/astral-sh/ohm-cargo/pull/21)
- [#22: Avoid embedding crate metadata in Ohm library artifacts](https://github.com/astral-sh/ohm-cargo/pull/22)
- [#25: Avoid saving unnecessary temporaries for cached relinking](https://github.com/astral-sh/ohm-cargo/pull/25)
- [#26: Skip public API hashing for terminal check targets](https://github.com/astral-sh/ohm-cargo/pull/26)
- [#27: Pipeline early-cutoff dependencies when public APIs change](https://github.com/astral-sh/ohm-cargo/pull/27)
- [#28: Skip relinking integration tests with unused package libraries](https://github.com/astral-sh/ohm-cargo/pull/28)
- [#29: Reuse integration executables across unused dependency changes](https://github.com/astral-sh/ohm-cargo/pull/29)

## ohm-rust-clippy

- [#31: Set up fork-owned Clippy CI](https://github.com/astral-sh/ohm-rust-clippy/pull/31)
- [#1: Backport statically combined late lint passes](https://github.com/astral-sh/ohm-rust-clippy/pull/1)
- [#2: Backport statically combined early lint passes](https://github.com/astral-sh/ohm-rust-clippy/pull/2)
- [#3: Backport cached macro-backtrace lookups](https://github.com/astral-sh/ohm-rust-clippy/pull/3)
- [#4: Backport doc-markdown lint early exit](https://github.com/astral-sh/ohm-rust-clippy/pull/4)
- [#5: Backport boxed-local parameter prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/5)
- [#6: Backport allocation-free associated item descriptions](https://github.com/astral-sh/ohm-rust-clippy/pull/6)
- [#7: Skip redundant-clone analysis for clone-free functions](https://github.com/astral-sh/ohm-rust-clippy/pull/7)
- [#13: Backport disabled documentation-lint guards](https://github.com/astral-sh/ohm-rust-clippy/pull/13)
- [#14: Backport allocation-free MinifyingSugg zero checks](https://github.com/astral-sh/ohm-rust-clippy/pull/14)
- [#15: Backport allocation-free documentation tab scanning](https://github.com/astral-sh/ohm-rust-clippy/pull/15)
- [#8: Backport ASCII fast path for Unicode lint scans](https://github.com/astral-sh/ohm-rust-clippy/pull/8)
- [#16: Backport inline_always attribute prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/16)
- [#17: Backport incompatible_msrv test-context deferral](https://github.com/astral-sh/ohm-rust-clippy/pull/17)
- [#18: Backport early-literal token prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/18)
- [#19: Backport cloned_ref_to_slice_refs shape prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/19)
- [#20: Backport single-component import prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/20)
- [#21: Backport unnecessary_mut_passed query deferral](https://github.com/astral-sh/ohm-rust-clippy/pull/21)
- [#22: Backport method-name prefilters](https://github.com/astral-sh/ohm-rust-clippy/pull/22)
- [#23: Backport or_fun_call method-name prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/23)
- [#24: Backport empty disallowed-methods guard](https://github.com/astral-sh/ohm-rust-clippy/pull/24)
- [#25: Port used-underscore name prefilters](https://github.com/astral-sh/ohm-rust-clippy/pull/25)
- [#9: Backport match_same_arms lint-level guard](https://github.com/astral-sh/ohm-rust-clippy/pull/9)
- [#26: Backport test-item crate prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/26)
- [#27: Backport span_contains_cfg source prefilter](https://github.com/astral-sh/ohm-rust-clippy/pull/27)
- [#10: Backport delayed external-macro checks](https://github.com/astral-sh/ohm-rust-clippy/pull/10)
- [#11: Skip nonstandard-macro analysis when the lint is disabled](https://github.com/astral-sh/ohm-rust-clippy/pull/11)
- [#28: Backport structural const-context prefilters](https://github.com/astral-sh/ohm-rust-clippy/pull/28)
- [#29: Backport deferred MSRV checks](https://github.com/astral-sh/ohm-rust-clippy/pull/29)
- [#12: Experiment with empty-attribute MSRV parsing fast path](https://github.com/astral-sh/ohm-rust-clippy/pull/12)

## ohm-rustfmt

- [#1: Set up fork-owned rustfmt CI](https://github.com/astral-sh/ohm-rustfmt/pull/1)
