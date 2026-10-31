# Linux native admission for mixed-profile generic sharing

The source-built candidate moved a checked, explicitly inline-hinted Rust generic from the O0 supplier to the O1 consumer on the native x86-64 target. The AArch64 cross build and a custom JSON target named after the host retained the supplier. The compiler came from feature commit `7562c319cd9dbd3c1aa99a5797638d05c2026fff`, transplanted onto signed -21 source `c79998a5cd143c445a4b2528f20953b176a65c5d`. The three compiler builds and native admission ran at QA commit `d1e77f9acf1bb19ceb72274b89a5aaa119fb8bf1`. [Hosted run](https://github.com/astral-experiments/ohm/actions/runs/41157899149) · [Source, build and enrollment](https://github.com/astral-experiments/ohm/tree/d1e77f9acf1bb19ceb72274b89a5aaa119fb8bf1/scripts/strict-mixed-generics)

## Offline replay

From this checkout, run the following with Python 3.10 or later. The reader checks the four original ZIPs, opens the recorded process streams, reads all six migrated crate metadata headers, and prints the executable hashes and observed graph transitions.

```sh
python3 -IB scripts/strict-mixed-generics/evidence/41157899149/verify.py
```

The four original Actions artifacts total 387,066 bytes. Their exact byte lengths and SHA-256 digests are in `verify.py`. The observation archives hold the SDK member manifests and compiler test logs. The native archive contains the raw Cargo JSON, diagnostics, process statuses, executable verdicts, extracted symbol records, and six actual metadata files. The manifest hashes identify the separately built SDKs. [Parent compiler observations](https://github.com/astral-experiments/ohm/actions/runs/41157899149/artifacts/13025383979) · [Candidate compiler observations](https://github.com/astral-experiments/ohm/actions/runs/41157899149/artifacts/13026182708) · [Legacy compiler observations](https://github.com/astral-experiments/ohm/actions/runs/41157899149/artifacts/13025971773) · [Native observations](https://github.com/astral-experiments/ohm/actions/runs/41157899149/artifacts/13025832165)

## Results

- The candidate passed the named `rustc_metadata` codec unit test and Rust's checked-in `ohm-profile-aware-shared-generics` run-make test. The parent, candidate and genuine untagged legacy compiler used the same bootstrap settings, stage0 identities and LLVM revision.
- Each compiler arm recorded 126 commands. Both metadata modes changed ownership of the hinted instance only for the eligible mixed-profile consumer and its repaired repeat. The `#[inline(never)]` and C-ABI function pointers retained their baseline ownership. Explicit sharing settings, homogeneous profiles, and seven debug-assertion, overflow and UB-check combinations preserved their observed behavior.
- The ordinary Cargo executable returned 17, then 29 after the source edit, then 17 after repair. Within each arm, the edited, repaired and profile-flipped executable hashes matched the corresponding independently empty build. The unchanged repeat had three fresh artifacts. All four malformed visits exited 101 and emitted the identical structured E0308 at `provider/src/lib.rs:13:32`. The mixed-profile executable bytes differ across the two compilers.
- Under an identical compiler version and forced incremental stamp, the 22-command migration sequence ran six genuine executables. The parent wrote graph generation 8 and metadata epoch 1. The candidate wrote generation 9 and epoch 2. The switches in both directions required a fresh graph even with the previous metadata prefix present. Each same-compiler repeat loaded its graph. Both foreign-epoch user crate reads failed with E0514. Both compilers loaded the genuine untagged equal-hash exporter from its selected sysroot, returned 42, and rejected it as a user dependency. The separately installed official Rust 1.99.0 ran its own control successfully.

This run measured source compatibility, compiled symbol ownership and executable behavior. Whole-Ruff instruction counts, elapsed time, and migration storage costs require their own measurements.
