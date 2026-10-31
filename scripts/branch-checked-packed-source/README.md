# GNU qualification for the corrected packed work-product reader

The isolated manual workflow on `charlie/qa-branch-checked-packed-source-20261031` bootstraps Rust `393b4b05a4bfa3f531a36023846f86236a6b71a9`. It runs on one GNU x86-64 worker with a 300-minute timeout and requires more than 32 GiB free before bootstrap. It uses the original strict Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd` and signed Wild. All fixtures use the normal rustup `+ohm` entry. The Cargo fixture sets only its opted-in branch-cache flag. There are no performance samples.

The 216,546-byte self-contained Git pack starts at the genuine old E commit. It includes 656 objects. In-tree verification reconstructs the complete candidate from the original public Rust source and the previously sealed F/K/E source. It verifies the rebased immediate parent `d14aab0e` has the old E compiler, library, bootstrap and tests. Base `6dbcba66` has the same four trees as F. Git comparison against the immediate parent permits only the native packed-object restore function, its unit test, and the existing packed-cache run-make.

The existing Linux suite runs the ten named incremental units, separate library/doc-test processes, seven real run-makes, six provider/syntax/repair visits, sixteen strict native-provider visits and four K/current-switch histories. The run-make now tests matching source recovery after both corrupt and conflicting input. Full manifest comparison permits changes to the necessary driver and its matching rustdoc among the 81 SDK files.

## Additional native checks

The workflow reacquires both official old-E ZIPs, reopens their existing native and selector receipts, restores every original SDK member, and separately restores F. The normal old and corrected two-crate Cargo fixtures each force physical recompilation of the leaf and its executable through 13 states. These include good packed-only input, identical or conflicting raw names next to it, corrupt streams/digests, symlink/FIFO, lock contention, malformed raw and an unaccompanied raw object. An independently corrupted **raw-only** work product remains outside the packed format's integrity boundary. Its legacy A17 result is recorded for each compiler.

Two further histories share one real cache and one installed compiler path per trial.

* The old compiler writes A17 and packed B29. Four independent histories then return using either old or corrected E. Trusted packed-only input must retain the source marker. Identical raw, different raw and corrupt packed input must each discard it on the corrected compiler and regenerate the complete clean B29 program. Old E must reproduce its wrong complete A17 on the real conflict.
* Old E writes B29. Genuine F recompiles that checkout with the source changed to 83. It carries the original packed29 inode and creates an incompatible raw83. Neither input is altered by the fixture. The corrected reader must discard the marked source and return exactly F's whole B83 executable and its own independent empty B83. Old E returns the same correct B83 while accepting the marked raw session.

Every supplemental Cargo/compiler invocation retains positive kernel file-descriptor opens and executable mmaps for the authenticated driver, full ELF and program-output evidence, typed Cargo records where applicable, and compressed source/packed native operands. The reader verifies the zlib frame, exact session/header, x86-64 ELF, filename BLAKE3 and SHA-256. The trace is a positive per-process driver witness. The genuine Cargo commands and probes are unscored.

## Reopen

Use Linux with Python 3.11 or later, GNU `b3sum`, Git and the two original artifact ZIPs named `first-session-linux-source-{driver,observations}.zip` in the same directory. Check out the exact QA head and run:

```sh
python3 -IB scripts/branch-checked-packed-source/locate_checked.py RUN QA_HEAD --media /path/to/original-zips
```

Restore the independently qualified driver only after both ZIPs pass. The first directory contains the three ordinary files from the already verified original F/K SDK ZIP (run 41199659076). The second contains the two regular members of the corrected driver's ZIP.

```sh
python3 -IB scripts/branch-checked-packed-source/restore_checked.py K_TRANSFER CORRECTED_TRANSFER NEW_SDK --qa QA_HEAD --run RUN --attempt 1 --manifest VERIFIED_MANIFEST_SHA256
```

The role E in the inherited transport is identified by the full product commit, driver and official archive. Earlier performance recordings belong to the old source. The 12-position Ruff protocol and runner boot exclusions are held separately.

For local review, `test_binding.py` checks registration and 11 admission refusals. `test_binding.py --native DIRECTORY` independently reopens the 38 real legacy contact visits, all matching program bytes and 15 falsification controls in a previously acquired contact. `inputs/rehearsal.json` records the local old-native outcomes. It does not qualify the new compiler.
