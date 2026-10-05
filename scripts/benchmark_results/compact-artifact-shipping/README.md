# Compact artifacts: shipping candidate

This continues the [prototype evaluation](../compact-artifact-prototypes/README.md).
The candidate is an opt-in native Linux format. Release source pins and automatic
defaults are unchanged. The shipping decision awaits the complete timing matrix.

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

## Measurement design

The frozen matrix has 312 build commands: two projects, four modes, three fresh
rounds, and 13 commands per cell. Each cell includes a clean build, no-ops,
three direct edits, three private-library edits, and three inline edits. Mode
order reverses in the middle round. Sequential edits share cache history; the
summary exposes per-round means rather than treating all nine edits as
independent runs.

| Mode | Compiler | Linker | Artifacts |
| --- | --- | --- | --- |
| baseline | Pristine Ohm source | Pinned shipped Wild 0.10.0 | Ordinary |
| standard | Candidate source | Candidate Wild fork | Ordinary |
| compact-raw | Candidate source | Candidate Wild fork | External-store objects, raw metadata, repaired prefix reuse |
| compact-archive | Candidate source | Candidate Wild fork | Self-contained compact archives with full raw metadata |

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

Storage is the whole lane: private target, shared build directory, incremental
state, scratch files, and any external store. Census deduplicates hard links and
reports both logical bytes and allocated filesystem blocks. CPU and sampled
process-tree peak RSS accompany wall time. Every command must pass its runtime
oracle, and each clean build must prove the requested on-disk format. An
unrelated compiler or sustained outside user CPU invalidates the run.

## Results and decision

Pending the complete, accepted matrix. The original prototype percentages do
not describe this candidate and must not be substituted for its measurements.

## Correctness and release integration

See [the correctness audit](audit-correctness.md) for exact-head evidence,
compatibility cases, failure diagnosis, and remaining platform coverage limits.
The compiler distribution rehearsal checks the actual tarball's Wild binary,
capability marker, licenses, and compiler driver. It is not a production
PGO/BOLT build or a published release.

## Source revisions

| Component | Revision |
| --- | --- |
| Pristine Rust | `348339ddae4288ebb3af97d204b19479fef8f5f2` |
| Candidate Rust | `e55e0485efc397741f4aaf861f1c74a281ac902f` |
| Shipped Wild source base | `e9a9b0cb6fd63a23cc7b93aafc931aadd5746be6` |
| Candidate Wild | `dba82ebe99d98adbfe6358215d456cdddb1877da` |
| Measurement Cargo | `018a2b93409433dc5bc05c5fce838ae69e9bc396` |
| Candidate Cargo option | `207626090e1fb9b405abd806a86c1b42bd2db5ff` |

The harnesses are in [harness/](harness/). The original benchmark core remains
frozen at SHA256 `ea7867f9f9a0f19ceb7d9c558aa7aa6758ae3e254878685fbc58768c65713cef`.
