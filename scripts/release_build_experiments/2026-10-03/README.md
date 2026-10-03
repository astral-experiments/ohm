# Release build experiments

These experiments measure three independent, opt-in changes against the compiler
and Cargo revisions in Ohm 1.99.0-1. They do not change release defaults or the
published development-build benchmarks.

The compiler and workload identities are recorded in [protocol.json](protocol.json).
Ruff and uv are measured at fixed source revisions. Within each comparison, the
compiler binary, build configuration, workload edit, and host remain the same.
The three changes have not been measured together.

## Completed measurements

This draft is being assembled while the remaining measurements finish. The
completed comparisons below have been independently checked against the raw
samples. Remaining runtime guards, direct compiler-flag timings, and the ThinLTO
dependency-cache experiment will be added separately.

| Early fat-LTO merging, Ruff  | Paired elapsed-time change | Pairs |
| ---------------------------- | -------------------------: | ----: |
| Entrypoint rebuild           |                     -2.37% |     4 |
| Cold compiled-artifact build |                     -1.50% |     3 |

These are geometric means of candidate/control ratios on one 32-CPU Linux host.
Every pair improves: 1.67–3.09% for edits and 0.98–1.78% for cold builds. Edit-build
peak child RSS is 4.07% lower, and the original-source executable is 0.68% smaller.
The last edit baseline had more resident-service activity; the first three pairs
alone improve by 2.13%. It is retained in the primary result.

The timings use the same PGO/BOLT release compiler with matched LLVM plugins.
The implemented compiler flag produces a byte-identical real Ruff executable and
an identical final fat-LTO pipeline in a separate locally built compiler. Its
parallel prelink trace interleaves within lines and is not claimed to match.
Direct timings of that unprofiled compiler remain a separate comparison.

[The compact Ruff packet](llvm/ruff.json) contains all accepted pairs, screening
alternatives, rejected artifact-restoration and trace comparisons, compiler and
source identities, cache-layout checks, and preliminary runtime checks. The
`raw_*` and log hashes identify the original captured bytes; the compact JSON is
formatted for this repository and is not a byte-for-byte copy of those captures.

The [generic-sharing draft](https://github.com/astral-sh/ohm-cargo/pull/132) has
completed fat-LTO builds on three uv hosts and two Ruff pairs. The two completed
16-CPU uv cohorts, including 30 runtime pairs per workload, are captured in
[the generic-sharing packet](generics/summary.json). Remaining host packets will
be added when their bounded runtime and ThinLTO work finishes.

| Generic sharing, uv      | Fresh build | Entrypoint rebuild | Library rebuild |
| ------------------------ | ----------: | -----------------: | --------------: |
| 16 CPUs, candidate first |     -19.49% |            -21.22% |         -21.01% |
| 16 CPUs, control first   |     -18.51% |            -21.50% |         -19.52% |

Each cell is one same-host, same-Cargo, same-compiler pair. Cold executables are
about 11% smaller. Runtime outputs and diagnostics match; all four paired
bootstrap intervals include no change. A retained 138 ms candidate outlier makes
one trio interval wide, so these short runtime samples do not establish a speedup.
The draft also records Ruff regressions and all three uv hosts; this evidence
packet is still being assembled.

## Comparisons

- **Early fat-LTO merging** runs LLVM's existing function-merging pass once more
  after combining the modules, before the main optimization pipeline. It keeps
  fat LTO and the optimization level unchanged.
- **LTO generic sharing** lets eligible optimized target crates reuse upstream
  generic instances. Cargo scopes the flag to units used only for LTO and the
  final LTO unit; host tools and mixed consumers keep their existing behavior.
- **ThinLTO dependency reuse** reuses optimized dependency objects when LLVM's
  cache key matches a validated previous work product. This requires incremental
  ThinLTO, a different build configuration from the projects' shipped fat-LTO
  profiles. Local modules retain their existing dependency-graph checks.

## Measurement boundaries

Cold builds start with empty compiled-artifact directories and warmed registry
downloads. They are not cold-filesystem or network-download benchmarks. Cargo uses
the host's normal concurrency: 32 logical CPUs for early merging and primary
generic-sharing measurements, and 16 for the migrated ThinLTO measurements and
independent uv generic-sharing confirmations. Timings from different hosts are
not pooled.

Edit measurements change real source and require a compiler invocation. An
unchanged source timestamp or a restored Cargo artifact namespace does not count
as a compiler rebuild. Entrypoint edits and library edits are reported separately.
Counterbalanced ordering reduces order effects; individual samples remain the
source of truth, including unsuccessful and excluded trials.

Final wall-time measurements disable compiler profiling and cache diagnostic
logging. Instrumented runs explain where time goes or verify a cache hit; their
times are not included in the performance comparisons. Locally built compilers
are compared with themselves with the experiment disabled. Absolute times from
those compilers are not compared with the PGO/BOLT-optimized release compiler.

The runners retain executable sizes and hashes, memory measurements, command and
environment provenance, and host interference records. Unrelated compiler
overlap invalidates a complete comparison pair. Normal resident services remain
running and their measured activity is disclosed. No unrelated processes or
cache directories are removed.

Runtime checks use saved binaries after compilation finishes. Ruff checks and
formats the same pinned CPython corpus. uv resolves pinned requirement inputs
against a prepared cache with networking disabled during timing. Observable
outputs are compared alongside the runtime samples. These workloads are guards
against observed regressions, not a comprehensive application performance suite.

## Interpretation

A change to elapsed time is `candidate / control - 1`; negative values are faster.
Comparisons apply only to their measured workload, compiler configuration, and
host. Small effects need repeated pairs. A neutral or negative experiment is
retained so reviewers can assess the tradeoff. Improvements from separate
experiments must not be added or multiplied into a combined claim.
