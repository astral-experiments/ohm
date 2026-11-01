# An ordinary workspace check after uv #20988

Adding Ohm Rust #296 and #306 reduced the median first workspace-root `cargo check` after a real edit from **28.475419 s to 17.531728 s** on these two local Linux stage1 compilers. The median of the six paired ratios was **1.627363596×**, with a 96.875% order-statistic interval of **1.552129081–1.659410896×**. All six pairs favored the stack. None reached 2×. The stock-first stratum had a median ratio of 1.622917856× and the stack-first stratum 1.631809337×. The predeclared threshold for opening a 2× confirmation was 1.80× median and at least one pair at 2×.

## Replay the clocks

The adjacent checksum identifies the distributed archive. From a directory containing the archive and `SHA256SUMS`, use a standard Python 3.10+ installation.

```sh
sha256sum -c SHA256SUMS
tar -xJf ohm-uv-20988-stage1.tar.xz
cd ohm-uv-20988-stage1
python3 -ISB verify.py
```

The verifier reads the original `edit-D.json` directly from each of the 12 unmodified per-arm ZIPs. It checks their SHA-256 digests against a second extraction, and matches the clock, exact Cargo argument vector, ordered dirty-unit list and trial with the original closed-session ledger. It reconstructs the alternating stock/stack and stack/stock ordering, six paired ratios, both order-stratum medians, and median seconds for each compiler. Clock arithmetic uses integer nanoseconds and exact fractions. The min–max median interval has nominal coverage `1 − 2 / 2⁶` under independent continuous paired observations. All six pairs used one discovery cohort on one host, with the same frozen parent state for each visit of each compiler.

## What changed

The edit is uv `b60da7ad468d5bb8a6b3dee7d7e54a47981f23c7` → `1979349b68dbaa936b98c0f409c1df0598fa72f1`. It changes workspace exclusion handling for normalized globs and escaped workspace roots, plus the workspace discovery benchmark. The lockfile digest is identical. Each timed visit started with its own arm’s restored A source and Cargo target, applied the complete historical edit while leaving HEAD on A, then ran the ordinary workspace command `cargo check --locked --offline -j8`. The timer surrounded Cargo and waited for its normal process tree to finish. All recurring background work stayed on the clock. [uv edit](https://github.com/astral-sh/uv/pull/20988/files)

| Local stage1 role | Rust base → repaired tree | Incremental epoch | Linked rustc driver SHA-256 |
|---|---|---:|---|
| Stock plus #318 | `008a21ac0d750dc9a1c18b7959d7e7984c03d887` → `1a0e58a855e1782a93cdf8c56b337fb4354142ef` | 43310 | `36cbcce59c0a2616abf699fa3bd91cc1ecce1805fcd224e6aae8bbb52135f170` |
| #296 + #306 plus #318 | `fa7a7899837d6a0f700f1df11f4a3a74a7a0f637` → `cb977189205aa931f080b57b9a8bb62ef98a316e` | 43309 | `e0b5f2f96ae0a77f1562159aaed26fd24f16d9bc64918cd54d25f79f8d7e0ac9` |

Both arms used signed Ohm −22 Cargo `ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770`, binary SHA-256 `3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871`. The loader receipts bind each measured launcher to its compiler driver and the SDK inventory records all 66 file identities. The comparison estimates the combined effect of #296 and #306 on this stage1 build. A release-trained SDK needs its own measurement. [#296](https://github.com/astral-experiments/ohm-rust/pull/296) · [#306](https://github.com/astral-experiments/ohm-rust/pull/306) · [#318](https://github.com/astral-experiments/ohm-rust/pull/318)

## Verify the output as well as the clocks

* Each original visit ZIP contains a 70-library manifest of real output paths, byte lengths and raw SHA-256 hashes. The packet builder rehashed all retained first-edit metadata binaries before export. The verifier joins each hash to its captured `rustc -Zls=root` output, validates its header, and compares the full decoded root and sorted dependency records with incremental and independently cold B. It also checks the 641-entry target/feature roster, positive and negative downstream consumer receipts, and the cross-arm stable crate IDs and public hashes.
* All six first-edit manifests were byte-identical within each compiler. Comparing with its independently cold B revealed **14 stock and 10 stack files** with different raw bytes. All decoded fields agreed. The packet preserves those per-file differences. It contains the captured decoder output and artifact digests. Generating a new decoder result from the original native binary requires the full local evidence.
* The four-state qualification predates the timing. Each compiler checked A, incremental B, and two independently cold builds of B. The three pairwise comparisons of B agree on all 8,291 stable definition fingerprints, 3,448 expansion fingerprints, allocation multisets and 70 workspace metadata roots. Hashed ordinary-completion and fixture receipts identify both native A and B behavior checks. The verifier checks these qualification records independently of its timing calculation.

## Repeating the measurement

Running `verify.py` replays existing data and uses no network, Cargo or rustc. A fresh physical timing run requires the exact repaired compiler trees and like-built SDKs above, the signed Cargo, the uv source and registry bank, the original snapshot-and-restore harness and an isolated Linux benchmark host. Preserve independent caches per compiler, all normal workspace features and background work, and the alternating order. The stage1 SDKs, uv sources, build products and host-specific setup are outside this archive. The archive lists its inputs in `FILES.json`; `case.json` includes complete source identities, original intake/registration hashes and the projected path-independent role information.
