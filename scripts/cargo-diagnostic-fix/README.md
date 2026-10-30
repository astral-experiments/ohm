# Cargo's repair after a failed check

The baseline is signed -21 Cargo source 2d44bd4a. The candidate 8c68d93d
requires a completed build before it will skip a unit dirtied by a dependency.
The worker reconstructs the genuine Git commits and 3,108 physical source
entries of each by applying two authenticated deltas to a private packaging
object seed. It builds each Cargo with the signed -21 compiler and the same
release features, then invokes each from an independent ordinary Rustup
toolchain pointing to the very same signed Rust compiler and standard library.

The 21 visits per source Cargo retain the previously frozen real Ruff check
of ty_project at Ruff 93526150, including the complete upstream edit, two
different failing sources, restoration, further edits, idle human and JSON
processes, and distinct empty builds. Six additional visits in those 21
verify a genuine deprecation warning at the edited, repeated, invalid and
repaired source states. Only real process starts can satisfy the compile
count checks. The registered difference requires one real ty_project check
to recover, an accurate warning, and then a normal Ron-only repeated check.

The separate in-tree receiver builds the candidate's exact testsuite once.
It locates the suite's actual child Cargo executable through the kernel and
runs the new regression and three neighboring healthy check cutoffs with
the same test binary against both independently compiled Cargo products.
The only swap is the ordinary executable inside the temporary integration
test target. The test source and product sources remain authenticated.
