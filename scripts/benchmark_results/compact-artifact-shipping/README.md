# Compact artifacts: shipping candidate

The candidate stores compact object files in self-contained archives with raw
Rust metadata. It removes the external store and its lookup/garbage-collection
requirements, while preserving ordinary consumers, static libraries, saved
relinking, and donor-independent worktrees.

The completed four-round comparison saved **19.1% of allocated build storage
on uv and 13.9% on Ruff**, after the edit sequence versus baseline. Existing application-function edits took about
0.08 seconds longer on uv and 0.13 seconds longer on Ruff; dependency-function
edits changed by less than 0.01 seconds and 0.27 seconds, respectively. The
synthetic Ruff inline-helper case cost 0.42 seconds. These are results for the
frozen Cargo `4a281305`, not a claim about all development edits. See the
[four-round results](four-round-results.md) for means, paired distributions,
ordinary-path costs, CPU, and memory observations.

The measured tradeoff supports an opt-in: the synthetic percentage reflects a
short rebuild, while the cost is a much smaller fraction of longer commands.
The scoped correctness/safety review found no remaining blocker. The current
Cargo rebase changed scheduling, so the remaining validation is the separate
current-Cargo confirmation described in the [evaluation](readiness.md).
Release pins and defaults remain unchanged.

## Implementation

The new format puts compressed `RCOBJ001` object members in ordinary `.rlib`
archives, together with raw Rust metadata. Incremental object files use the same
compact representation. Each archive is self-contained with respect to its
metadata and object payloads; normal dependencies still apply. There is no
external object store, ancestor lookup, or separate garbage collector.

Cargo exposes `-Zohm-compact-artifacts=yes`, disabled by default. It selects the
matching bundled Wild, preserves explicit compression tuning, and otherwise uses
the fast profile. It requires native `x86_64-unknown-linux-gnu`, full metadata,
and a matching format capability marker. Incompatible linker selection,
cross-crate LTO, linker-plugin LTO, and packed split DWARF are rejected before
compiling. Normal native-library and rpath arguments remain supported.

Metadata-prefix reuse is restored. Static libraries export ordinary ELF objects;
the same Ohm compiler can consume a compact dependency with an ordinary system
linker, including doctests. Saved relinking carries the metadata it needs.
Worktree seeding and cleanup use Ohm's existing artifact lifetimes.

The Wild fork is based on the shipped **0.10.0**, rather than the prototype's
newer unreleased linker. The release workflow can build it from an exact source
revision using a pinned compiler. Both compiler-build platforms obtain the
shared format crate; only Linux packages the linker and its capability marker.

## Review and evidence

The [correctness audit](audit-correctness.md) covers native Linux compiler,
package-installation, lifecycle, ordinary-consumer, replay, alignment, and
worktree checks, plus ordinary macOS execution and unsupported-target
rejection. The [safety review](safety-review.md) covers decoding bounds, shared
inode preservation, cache identity, metadata reuse, and CI credential scope.

The [current evaluation](readiness.md) separates the four-round compiler
comparison from the current Cargo integration check and provides portable
receipt audits. The [initial study](initial-study.md) retains the earlier
synthetic-edit findings and external-store comparison; its 32.4%/24.5% storage
reductions do not describe the proposed self-contained format.

Compiler CI requires dedicated `OHM_SOURCE_APP_CLIENT_ID` and
`OHM_SOURCE_APP_PRIVATE_KEY` credentials for a read-only App installed on
`ohm-wild`. Its jobs currently stop at token creation, before compiler checks.
Local validation is recorded separately. The release App remains separate;
no credentials or repository settings were changed. A full production
PGO/BOLT distribution and hostile-input fuzzing are outside this validation.

The implementation is split across [coordinator #140](https://github.com/astral-sh/ohm/pull/140),
[Rust #157](https://github.com/astral-sh/ohm-rust/pull/157),
[Cargo #134](https://github.com/astral-sh/ohm-cargo/pull/134), and
[Wild #32](https://github.com/astral-sh/ohm-wild/pull/32).
