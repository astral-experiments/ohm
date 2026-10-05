# Compact artifacts: automatic storage and linker compatibility

The compatibility revision enables compact storage with Ohm defaults on native
x86-64 GNU Linux. Explicit linker choices remain supported, and unsupported
targets or older toolchains automatically retain ordinary storage. Users can
disable compact storage with `-Zohm-compact-artifacts=no`.

**Recommendation: adopt automatic compact storage on supported Linux
toolchains, retaining the explicit opt-out.** The 90-command compatibility
confirmation passed every runtime check. The normal bundled-Wild path saves
13.9–19.3% of settled build storage for mean edit costs of 0.09–0.19 seconds.
Custom linkers work through an adapter, with a larger measured cost described
below. The [compatibility evaluation](compatibility.md) records the configuration
contract, source review, native proof, and remaining release-validation limits.

The implementation stores compact object files in self-contained archives with
raw Rust metadata. It removes the compiler's external-store experiment and its
lookup/garbage-collection requirements, while preserving ordinary consumers,
static libraries, saved relinking, and donor-independent worktrees.

## Measured tradeoff

All **90/90 commands** passed with no exclusions. These figures compare
automatic compact storage with an explicit storage opt-out using the same
compiler, Cargo, and Wild binaries. They are means across two fresh rounds.
The compiler source patch is `4790daed`, the measured Cargo patch is `20b9d1fd`,
and Wild is `9179eb98`. Final Cargo `76793c44` additionally fixes an inactive-path
configuration read and test coverage; its new early return is not reached in
any measured configuration. Final-build functional proof is separate from the
frozen timing build.

Storage is settled allocation **after the edit sequence**, covering the whole
private target, shared-build subtree, and scratch lane, with hardlinks counted
once. It is not peak disk use or unique physical CoW allocation.

| Project |  Ordinary |   Compact | Disk reduction |
| ------- | --------: | --------: | -------------: |
| uv      | 3.396 GiB | 2.740 GiB |          19.3% |
| Ruff    | 2.565 GiB | 2.208 GiB |          13.9% |

Existing source-function edits show the following whole-command wall times.
Each mean contains three sequential edits in each of two rounds, not six
independent repetitions.

| Project | Edit                 | Ordinary |  Compact | Extra time |
| ------- | -------------------- | -------: | -------: | ---------: |
| uv      | Application function |  7.771 s |  7.935 s |   +0.164 s |
| uv      | Dependency function  | 22.664 s | 22.750 s |   +0.086 s |
| Ruff    | Application function |  1.809 s |  1.933 s |   +0.125 s |
| Ruff    | Dependency function  | 21.533 s | 21.721 s |   +0.188 s |

Clean-build means increase from 141.120 to 141.629 seconds on uv (+0.36%)
and from 124.587 to 125.895 seconds on Ruff (+1.05%). Individual paired edit
differences vary in sign; the observed mean costs are small relative to the
measured longer commands. This does not establish constant overhead or how
frequently each edit shape occurs in everyday development.

The custom-linker arm explicitly selects the same Wild through user
configuration, which exercises ordinary-input materialization. Ruff application
edits take 3.666 rather than 1.933 seconds (+1.733 seconds), and library edits
take 23.481 rather than 21.721 seconds (+1.761 seconds). Settled storage is
2.250 GiB, still 12.3% below ordinary storage. These are costs of the whole
custom configuration, including cache admission; they do not isolate decoding.
We retain this compatible path and document the opt-out for users who prefer
lower edit latency to storage savings.

The [compatibility results](compatibility-results.md) retain paired medians,
observed ranges, round variation, no-ops, CPU, and memory. Some phases have
higher sampled process-tree RSS; disk savings do not establish a memory
benefit. The study uses development profiles and non-PGO/BOLT compiler builds
on one Linux host.

The earlier [156-command comparison](current-cargo-results.md) and
[416-command study](four-round-results.md) retain their separate pristine-compiler
baselines and synthetic-inline cases. They are not pooled with this confirmation.
The earlier +0.422-second Ruff synthetic-edit result remains a workload
tradeoff; its percentage alone is not an adoption blocker.

## Implementation

The new format puts compressed `RCOBJ001` object members in ordinary `.rlib`
archives, together with raw Rust metadata. Incremental object files use the same
compact representation. Each archive is self-contained with respect to its
metadata and object payloads; normal dependencies still apply. There is no
external object store, ancestor lookup, or separate garbage collector.

Cargo automatically enables compact storage with Ohm defaults when the host and
target are native `x86_64-unknown-linux-gnu` and the toolchain provides the
`compact-artifacts-v2` capability marker. Automatic selection falls back to
ordinary storage on older toolchains, other targets, or explicit metadata and
format overrides. Explicit `-Zohm-compact-artifacts=yes` diagnoses unsupported
storage configurations; `-Zohm-compact-artifacts=no` disables only this feature.

The bundled Wild consumes compact objects directly. When a configuration,
profile, command, or build script selects another linker, rustc creates private
ordinary ELF inputs for that link while preserving compact cached objects and
archives. Thin/fat LTO can extract embedded bitcode from compact dependencies;
packed DWARF receives ordinary inputs for packaging. Unpacked debug objects are
retained as ordinary files for debuggers without changing shared cache inodes.
Linker-plugin LTO preserves raw bitcode and the user's linker selection; the
selected linker still needs a compatible LLVM implementation.

The v2 marker identifies the compiler's expanded consumer support; the compact
object encoding is unchanged. Explicit compression tuning is preserved, with
the fast profile used otherwise. Normal native-library and rpath arguments
remain supported.

Metadata-prefix reuse is restored. Static libraries export ordinary ELF objects;
the same Ohm compiler can consume a compact dependency with an ordinary system
linker, including doctests. Saved relinking carries the metadata it needs.
Worktree seeding and cleanup use Ohm's existing artifact lifetimes.

The Wild fork is based on the shipped **0.10.0**, rather than the prototype's
newer unreleased linker. The release workflow can build it from an exact source
revision using a pinned compiler. Both compiler-build platforms obtain the
shared format crate; only Linux packages the linker and its capability marker.

## Review and evidence

The [current compatibility review](compatibility.md) covers automatic selection,
linker precedence, LTO, DWARF, cache freshness, and the final Cargo build.
The [portable correctness evidence](correctness/compatibility/README.md) and
[performance evidence](measurements/compatibility/README.md) reproduce their
recorded checks without devbox access. Native compiler suites, 32 installed
policy checks, and the final Cargo build's 15 focused tests and five runtime
cases pass. Independent source review found no remaining blocker within this
scope.

The [earlier correctness audit](audit-correctness.md) covers native Linux compiler,
package-installation, lifecycle, ordinary-consumer, replay, alignment, and
worktree checks, plus ordinary macOS execution and unsupported-target
rejection. The [safety review](safety-review.md) covers decoding bounds, shared
inode preservation, cache identity, metadata reuse, and CI credential scope.

The [previous compiler evaluation](readiness.md) separates the four-round compiler
comparison from its later Cargo integration check and provides portable
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
