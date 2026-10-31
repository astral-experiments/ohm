# Repaired Ruff diagnostics and both Cargo collectors

One release-style Linux Cargo executable included the repaired-check fix, the shared-cache mount fix and the private-target mount fix. The qualification retained signed Ohm `1.99.0-21` rustc, its driver and its bundled Wild. Cargo's source was `b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b`, its Git tree was `c8d0e89c4226add0ae40b6604025f5e7b04489f5`, and its 51,111,560-byte executable had SHA-256 `f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f`. All five jobs passed. [Cargo source](https://github.com/astral-experiments/ohm-cargo/commit/b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b) · [Native qualification](https://github.com/astral-experiments/ohm/actions/runs/41149649623)

| Workflow | Signed `-21` | Combined Cargo |
| --- | --- | --- |
| Repair a real Ruff type error in a previously poisoned target | Later successful checks reprinted E0308, including after replacing Cargo with a rebuild of its signed source | The first check restored the original warning with 304 rustcs and 48 links, matching the empty build. Further checks compiled only Ron and ran zero linkers. All 19 visits are retained. |
| Shared GC with an existing bind mount in a retiring namespace or marked trash | Unlinked the outside file in each case and exited 101 | Preserved both outside files, reclaimed a healthy sibling and exited 0 |
| Bind a directory into the shared cache after the collector starts | Unlinked the outside sentinel and exited 101 | Preserved the name, content and link count, reclaimed the healthy sibling and exited 0 with both mount resolvers |
| Move a discovered private target directory outside the target and bind the same inode back | The previously captured signed command deleted its outside file and exited 101 | Both the native `openat2` path and the forced `ENOSYS` fallback preserved the outside file and exited 0. The fallback made 102 successful mount-ID reads. |

The private signed negative, the rejected first fix, and the independent ext4 and overlay controls are preserved separately. On the public #308 source, the private collector respected the held profile lock, then reclaimed 28 eligible files once unlocked. [Private-target original records](https://github.com/astral-experiments/ohm/tree/2dc85901b87e5df168bf6b0cbc727f18c9f524b2/scripts/private-gc-overlay/evidence)

The same Cargo source passed all eight ordinary CI jobs. Linux passed 4,826 tests plus 15 pinned Ohm cases. macOS passed 4,798 tests plus eight pinned Ohm cases. Both complete suites included the two affected ready-test cases. The full libtest name inventory, platform-specific ignores and two macOS storage-observer setup failures are preserved. [Linux and macOS verdicts and offline replay](https://github.com/astral-experiments/ohm-cargo/tree/74b503ed1d97cc9bafe13879cef57fc2129f408a/qa/combined-cargo-native)

The five ZIPs are the original GitHub artifact bytes. `artifacts.json` records each GitHub ID, size and digest. The verifier checks those bytes, release-build output, runtime identities, file contents and link counts, kernel observations, compiler and linker counts, and per-visit Ruff diagnostics. This command reproduces the stored summary from this directory.

```sh
python3 -IB verify.py | cmp - summary.json
```

The corpus here covers these three specific fixes. The separate comparison with the direct parent of #294 examines the older native-link marker when a library appears in the linker's own search directory. [Original stale native result](https://github.com/astral-experiments/ohm/tree/927e20bcad028e5ed4290a58bd330a258ee5da41/scripts/ohm-gnu-syscall/evidence/release-reader-compatibility/linux-unicode-implicit-wild-search) · [Matched source builds with isolated outputs](https://github.com/astral-experiments/ohm/actions/runs/41150601667)
