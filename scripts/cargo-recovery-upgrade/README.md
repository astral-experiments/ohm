# A signed-to-source upgrade after Cargo has accepted a stale diagnostic

This separate qualification reopens final Cargo 58f94004, its three genuine
Git commit objects after released Cargo 2d44bd4a, and the signed -21 rustc
used throughout. It first runs the enrolled 42 source-parent and source-fix
Ruff checks and warning controls. The in-tree receiver finds the real unit
test for inconsistent short and JSON fingerprints in the native library
suite and reopens the repaired-test regression and three healthy neighbors.

The upgrade uses a stable, physical Rustup alias, root paths, normal source
and fingerprint stores. It uses the actual signed -21 Cargo to produce
the original valid 16-byte success marker paired with a failed type error.
The valid source has a deprecation warning and the failing source removes it.
Returning to the valid source on old Cargo must replay the stale error.
The source-built fixed Cargo then replaces just the Cargo executable at
the same location. The study binds source bytes, mtime, each preexisting
fingerprint, driver inode, ctime and whole hash on both sides. It requires
the real warning back, a fresh typed verdict, and a subsequent healthy skip.

The signed Ruff case keeps its missing foreign-span input and real Ron.
A separate two-crate ordinary check must first demonstrate a poisoned
completely fresh old visit with zero compiler processes. Its upgraded
recheck must restore the warning, followed by a zero-compiler new visit.
A defaults-off same-path upgrade, a positive forced missing-output check,
and a distinct empty Ruff build serve as separate controls.
