# Release build experiments

Three independent opt-in experiments against Ohm 1.99.0-1, measured on Linux
x86-64 devboxes at default Cargo concurrency. [protocol.json](protocol.json)
records the exact compiler, Cargo, workload revisions, and implementation PRs.
Release defaults and the published development-build benchmarks are unchanged.
The changes have not been measured together.

## Results

| Experiment                                                                 | Measured build result                                                                                         | Scope                                                                         |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| [LTO generic sharing](https://github.com/astral-sh/ohm-cargo/pull/132)     | uv fresh builds 18.51–24.94% faster; entry rebuilds 21.22–21.77% faster; library rebuilds 18.52–21.01% faster | One fat-LTO pair on each of three hosts; Ruff regresses                       |
| [Early fat-LTO merging](https://github.com/astral-sh/ohm-rust/pull/154)    | Ruff fresh builds 1.50% faster; entry rebuilds 2.37% faster                                                   | Three fresh-build and four edit pairs; uv flat/mixed                          |
| [ThinLTO dependency reuse](https://github.com/astral-sh/ohm-rust/pull/155) | Final evidence packet pending                                                                                 | Requires incremental ThinLTO; remaining library/runtime validation is running |

The generic-sharing and early-merging packets are complete. This draft is still
being assembled while the dependency-cache lane finishes its bounded cohort.

## LTO generic sharing

Cargo enables generic sharing only for eligible optimized final LTO units and
dependencies used solely as LTO bitcode. Host tools, standard-library builds,
and dependencies with mixed consumers retain their existing behavior. Every
comparison uses the same candidate Cargo executable with the option off and on.

The uv improvement repeats across 16- and 32-CPU hosts and both orders. Its
original-source executables are about 11% smaller. Ruff goes the other way:
two counterbalanced fat-LTO pairs give geometric-mean slowdowns of 3.52% fresh,
5.80% for entry edits, and 1.84% for library edits, with a 1.31% larger binary.

Thirty runtime pairs per workload preserve outputs and diagnostics. Ruff's
fat-LTO formatter is 0.71% slower in the sample (paired 95% bootstrap interval:
0.44–0.99% slower); lint is inconclusive. Short uv resolver measurements vary
across hosts and include a retained outlier, so they do not support a general
runtime speedup claim.

Single-pair ThinLTO screens are separate, exploratory profile comparisons.
Generic sharing reduces uv fresh-build time by 13.09% and entry-rebuild time by
31.81%. For Ruff it reduces fresh-build time by 3.72%, leaves entry rebuilding
roughly unchanged, and increases binary size by 7.02%. Ruff's ThinLTO runtime
samples are 3.06% slower for lint and 0.97% slower for formatting. These
tradeoffs support retaining an opt-in experiment.

[All samples and provenance](generics/summary.json), [tables](generics/RESULTS.md),
and [reproduction instructions](generics/README.md) include 51 build samples and
720 measured runtime samples, the earlier global-flag screens, rejected
preflights, exact frozen helpers, compiler-command scope audits, and raw archive
receipts. The raw Ruff archive stores repeated streams by content hash while
preserving every original path, byte length, and digest.

## Early fat-LTO merging

The compiler runs LLVM's existing function-merging pass after linking modules
and before the main fat-LTO optimization pipeline. Optimization level and LTO
mode stay unchanged. The implementation is disabled by default and leaves
instrumented, custom, and incompatible pipelines unchanged.

Every Ruff pair improves: 1.67–3.09% for edits and 0.98–1.78% for fresh builds.
Edit-build peak child RSS is 4.07% lower; the executable is 0.68% smaller. The
last edit baseline had more resident-service activity; retaining only the first
three pairs gives a 2.13% improvement. All four remain in the primary result.

Timings use the same PGO/BOLT release compiler with matched LLVM plugins. The
implemented flag produces a byte-identical real Ruff executable and an identical
complete final fat-LTO pipeline in a separately built compiler. Parallel prelink
traces interleave within lines and are not claimed to match. A separate native
flag pair with that unprofiled compiler takes 240.816 → 233.852 seconds (2.89%
faster); it is contextual and is not pooled with the shipping-compiler results.

The fixed uv cohort is inconclusive: entry pairs change by −2.83% and +1.99%,
and the fresh-build pair by −0.095%. The uv executable is 1.41% smaller. All
samples remain, including their recorded background activity.

Twenty-four final runtime pairs per workload preserve outputs and diagnostics.
Ruff lint has a noisy 1.78% slowdown and format-check is effectively flat at
0.08% faster. uv resolver timings have large outliers on opposite variants;
no runtime throughput claim is made. Ruff format-check returns the same expected
status 2 for intentional invalid-syntax fixtures; it is not a clean formatter run.

[Ruff measurements](llvm/ruff.json), [native-flag and final Ruff validation](llvm/ruff-validation.json),
[uv measurements](llvm/uv.json), and [reproduction instructions](llvm/REPRODUCE.md)
include unsuccessful screens and rejected cache-restoration/trace comparisons.
The core compiler test passes; profiler-specific cases were capability-skipped
because the locally built compiler lacks the profiler runtime.

## Measurement boundaries

Fresh builds start with empty compiled-artifact directories and warmed registry
downloads. They are not cold-filesystem or network-download benchmarks. Default
concurrency is 32 logical CPUs for early merging and primary generic-sharing
runs, and 16 for the cache lane and independent uv generic-sharing confirmations.
Compare within each host; raw elapsed times from different hosts are not pooled.

Edit measurements change actual source and require compiler work. A restored
Cargo artifact namespace does not count as a rebuild. Entrypoint and library
edits remain separate. Each candidate/control pair uses the same compiler,
configuration, source edit, and host; order is counterbalanced where repeated.
Locally built compilers are compared with themselves, separately from the
PGO/BOLT release compiler.

Final wall-time samples disable compiler profiling and cache diagnostics.
Instrumented runs explain mechanisms and are excluded from performance claims.
Unrelated compiler overlap invalidates a complete pair. Resident services remain
running, with measured interference retained. Peak child RSS is a per-process
high-water measurement, not aggregate concurrent-build memory.

Runtime checks use original-source saved executables after compilation stops.
Ruff uses pinned CPython; uv resolves pinned inputs offline against a prepared
public PyPI cache. Full status, output, and diagnostic checks accompany timing.
These workloads are sampled guards, not a comprehensive runtime performance
suite. Each packet documents its exact corpus and permitted normalization.

A time change is `candidate / control - 1`; negative is faster. Repeated-pair
headlines use geometric means of those ratios. Single pairs are directional.
Raw-capture and log hashes identify original bytes; publication manifests identify
formatted checked-in files. Frozen measured harnesses are preserved byte for byte.
Neutral and negative experiments remain visible. Do not add or multiply these
independent speedups into a combined claim.
