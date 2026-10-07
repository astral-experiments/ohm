# Compact build artifacts

Ohm toolchains with the `compact-artifacts-v2` capability enable compact storage
by default on native `x86_64-unknown-linux-gnu`. Older toolchains, other targets,
and explicit artifact-format overrides retain ordinary storage.

```sh
cargo +ohm build
cargo +ohm -Zohm-compact-artifacts=no build
```

The opt-out disables storage compression independently of other Ohm defaults.
`-Zohm-defaults=no` also disables automatic compression; explicit
`-Zohm-compact-artifacts=yes` requires a supported target, matching capability,
and compatible storage settings.

Rust libraries remain self-contained `.rlib` archives with directly readable
metadata and compressed object members. Incremental objects use the same format.
Artifacts follow the existing target and shared-build directory lifetimes;
`cargo clean` removes workspace artifacts and retains the shared registry cache.
No separate object store or garbage collector is required.

Bundled Wild reads compact inputs directly. Explicit linker choices retain their
precedence: rustc supplies private ordinary inputs to other consumers without
changing cached archives. Final executables and shared libraries use ordinary ELF;
static-library exports contain ordinary objects. Saved relinking and doctests
remain supported. Thin/fat LTO can extract embedded bitcode, linker-plugin LTO
preserves raw bitcode and the selected linker, and debug packaging receives
ordinary objects when needed. A plugin linker must support the producer's LLVM.

## Measurements

In a 90-command Linux comparison, compact storage reduced settled build allocation
by 19.3% for uv and 13.9% for Ruff. Mean application/library edit costs increased by
0.09–0.19 seconds; clean builds increased by 0.51–1.31 seconds. The comparison used
two fresh rounds, eight jobs, and non-PGO/BOLT compiler builds. Sequential edits
within each round are not independent repetitions.

Selecting a custom linker configuration added about 1.7 seconds per Ruff edit
relative to direct Wild, while retaining 12.3% storage savings over ordinary
artifacts. That cost includes cache-admission effects; it does not isolate decoding.
Allocation covers settled target, shared-build, and scratch data, not peak storage
or unique physical CoW extents.

The [archived evaluation](https://github.com/astral-sh/ohm/tree/benchmark-evidence-2026-10-07-compact-artifacts/scripts/benchmark_results/compact-artifact-shipping)
retains exact source and binary identities, current and earlier measurements,
correctness checks, limitations, and the complete evidence bundles.
