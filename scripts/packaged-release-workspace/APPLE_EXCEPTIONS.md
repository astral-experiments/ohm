# Twelve full-file differences in Ruff’s binary test harness

On the real two-file `ty_server` edit, each released compiler linked the changed e2e executable and passed both its old and new test. Its catalog went from 194 to 195 tests. On unchanged commands, physical Xcode calls fell from 99 on `-20` to 65 on `-21`. Of the 83 returned test programs, 81 and 60 respectively were relinked. The complete native run, source enrollment and package identities are recorded in the [original workflow](https://github.com/astral-experiments/ohm/actions/runs/41110305000).

The original whole-workspace gate failed. At each successful warm visit on both releases, 82 of 83 programs passed its same-release, same-source native image comparison. The exception was the `ruff` binary test harness in `crates/ruff`. Its complete bytes differed at cold, unchanged old, edit, both unchanged new visits, and repair. That harness had no runtime test in this study. The independent cold-to-cold pair already reproduced the difference on each release. The archive contains one empty new build per release.

The diagnostic reopens the 16 needed original Mach-O programs, their actual signed Xcode linker processes and held arguments. On each pair, all 15 file-backed sections match. The only changed bytes are 18–21 bytes in the invocation salts of three directly linked CGUs, with exclusive `N_OSO` ownership, and 31–32 bytes in the corresponding valid CodeDirectory hash. The complete `-20` programs have 1,676 signed pages each. The `-21` programs have 1,672. For each release the diagnostic rejects a validly re-signed altered instruction, a validly re-signed changed symbol owner and a missing real linker input. The original gate retains its recorded failure.

Download the [original 1,476,457,114-byte ZIP](https://github.com/astral-experiments/ohm/actions/runs/41110305000/artifacts/13004433435). Its SHA-256 is `35cf3c8f6014ac1c877307cc05bad250b160fe10691f8fa22cba2389b19130c0`. Run the verifier from this packaging checkout. It checks the complete ZIP hash before resolving any evidence and compares its reconstruction to the compact checked-in receipt.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13004433435/zip > ruff-83-macos.zip
python3 -IB scripts/packaged-release-workspace/apple_exceptions.py ruff-83-macos.zip
```

The original sources and whole-workspace reopener are pinned at [`03e14718`](https://github.com/astral-experiments/ohm/tree/03e1471808f89177a3382d7253ba3da5e67c26e8/scripts/packaged-release-workspace).
