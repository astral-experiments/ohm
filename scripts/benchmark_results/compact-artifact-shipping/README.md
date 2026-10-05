# Compact artifacts: ready for opt-in review

**Decision: ship as an opt-in for native x86-64 Linux.** The completed evidence
supports trading modest absolute rebuild costs for substantially smaller build
storage. Keep the option disabled by default; it is not a general speed or
memory optimization.

The implementation stores compact object files in self-contained archives with
raw Rust metadata. It removes the compiler's external-store experiment and its
lookup/garbage-collection requirements, while preserving ordinary consumers,
static libraries, saved relinking, and donor-independent worktrees.

## Measured tradeoff

The current Cargo confirmation completed **156/156 commands** with no failures
or exclusions; its independent audit passed **28,855 checks**. The following
figures are means across two fresh rounds, using current Cargo `6333daf7`, Wild
`9179eb98`, and the verified compiler sources in Rust `36f01299`. Baseline uses
the pristine compiler with the same Cargo and Wild, rather than an installed
release with different build optimization.

Storage is settled allocation **after the edit sequence**, covering the whole
private target, shared-build subtree, and scratch lane, with hardlinks counted
once. It is not peak disk use or unique physical CoW allocation.

| Project |  Baseline |   Compact | Disk reduction |
| ------- | --------: | --------: | -------------: |
| uv      | 3.432 GiB | 2.777 GiB |          19.1% |
| Ruff    | 2.564 GiB | 2.207 GiB |          13.9% |

Existing source-function edits show the following whole-command wall times.
Each mean contains three sequential edits in each of two rounds, not six
independent repetitions.

| Project | Edit                 | Baseline |  Compact | Extra time |
| ------- | -------------------- | -------: | -------: | ---------: |
| uv      | Application function |  7.232 s |  7.657 s |   +0.425 s |
| uv      | Dependency function  | 22.988 s | 22.913 s |   -0.075 s |
| Ruff    | Application function |  1.944 s |  1.905 s |   -0.039 s |
| Ruff    | Dependency function  | 21.234 s | 21.489 s |   +0.255 s |

Clean-build means are within 0.7 seconds of baseline on both projects, whose
builds take roughly 125–143 seconds. The ordinary candidate also has small
measured costs with compact mode disabled: uv's application edit adds 0.282
seconds and its clean build adds 1.912 seconds versus baseline. The option's
additional application-edit cost over that ordinary candidate is 0.144 seconds
on uv and 0.020 seconds on Ruff. Leaving the feature off does not promise zero
compiler overhead.

The separate **four-round, 416-command** study with frozen Cargo `4a281305`
corroborates the storage savings. Its largest positive mean edit delta versus
baseline is the synthetic Ruff inline case: 0.422 seconds on a 2.671-second
rebuild. The current-Cargo confirmation measures 0.009 seconds for that same
class; these are separate datasets, not proof that changing the scheduler
caused the difference. The older cost is retained as a workload tradeoff, and
its large percentage alone is not an adoption blocker. Costs are a much smaller
fraction of the measured longer commands; these observations do not establish
a constant overhead or the frequency of edit types in everyday development.

See the [current-Cargo results](current-cargo-results.md) and
[four-round results](four-round-results.md) for paired medians, observed ranges,
round variation, no-ops, CPU, and memory. Some edit phases have higher sampled
process-tree RSS; the disk savings do not establish a memory benefit. Both
studies use development profiles and non-PGO/BOLT compiler builds on one host.

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
