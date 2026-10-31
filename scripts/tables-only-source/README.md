# First-checkout table packing on GNU

This manual job builds Rust `a653d40da8cd7e13a6e6c10ac6ebfeb224945c73` (T), directly on the frozen #274 head `f70612039692c9ec6abf67d8921f4b5085c0f101`. The compiler, library and tests at that base are identical to those at `c6fe8ecda65452c105f85367a009af80cbb5efbc` (F), whose complete tested GNU SDK is available from the original source run. The base differs from that original in one CI workflow. The two source packs contain exactly 387 and 14 Git objects. T changes three paths and keeps F's packed-table encoder. [Original GNU source run](https://github.com/astral-experiments/ohm/actions/runs/41199659076)

With the branch cache enabled on Linux, T packs the first successful Git session's eligible dep-graph and query-cache tables before normal publication. The modified checked-in run-make requires both packed files, then raw files on a same-branch edit and after a deliberately damaged first cache. Its ordinary opt-out, selected-branch, unchanged alternate, corruption, runtime and independent empty controls still run. The option remains default-off, and the two tables are the only added packed payloads. The job qualifies source and behavior.

The worker authenticates both original ZIPs, the unchanged 81-file F installation, eight native incremental units and seven named run-makes. It builds T with the original bootstrap command and checks all 81 installed members before and after testing. The permitted binary differences are the compiler driver and its matching rustdoc. The driver must change. T must pass the eight Linux units, seven run-makes and operational Cargo/rustc/rustdoc checks. Its ordinary provider fixture performs six builds. A further sixteen compare eight warm cases to independent empty builds under the same strict Cargo and stock Wild, including priority, same-stat replacement, malformed input, repair and removal.

Four fresh mixed histories exercise a T-packed cold session read immediately or after switching by F, and an F raw or switch-packed session read by T. They check the actual mapped compiler, table reads, decoded mmap, marker hardlink, runtime values 17 and 29, wrong-value exits and equal returned/independently empty A ELFs. A separate empty cache must reject an asserted successful load. All raw observations are retained under `T/` in `tables-only-linux-source-observations`. The success-only `tables-only-linux-source-driver` contains `manifest.json` and `T-delta.tar.zst`; reconstructing it over the authenticated original F must reproduce all 81 files. The manifest binds the source, test, native, mixed-reader and delta digests.

## Offline replay

Supply the existing Rust Git repository, a packaging checkout with the trusted builder tree at `a4afd181ae07107de6174a17a4ec189061fd18aa`, and a directory containing `branch-return-source-sdk.zip` and `branch-return-source-observations.zip` from run 41199659076. This reads the original media and writes only temporary files. The optional final argument replays four real K/E mixed histories to qualify the verifier interface independently of the pending F/T result. [Historical mixed-reader controls](https://github.com/astral-experiments/ohm/actions/runs/41227867294)

```sh
(cd scripts/tables-only-source && sha256sum --check SHA256SUMS)
python3 -IB scripts/tables-only-source/qualify.py preflight "$RUST_GIT"
python3 -IB scripts/tables-only-source/test_preflight.py \
  "$RUST_GIT" "$TRUSTED_PACKAGING" "$ORIGINAL_F_MEDIA" \
  --historical-mixed "$ORIGINAL_E_MEDIA" > replay.json
cmp replay.json scripts/tables-only-source/offline-preflight.json
```

The workflow accepts only an initial manual dispatch on `charlie/qa-tables-only-source-20261031` in `astral-experiments/ohm`. The required `reviewed_head` input must equal the exact revision checked out by Actions.

After a successful T qualification, authenticate the official source job and the two T artifact ZIPs, then read the manifest SHA from `T/qualified.json` in the observations ZIP. From the same QA checkout, restore into a new directory. The first input is the extracted original SDK-transfer ZIP, and the second is the extracted T driver-transfer ZIP.

```sh
python3 -IB scripts/tables-only-source/qualify.py restore \
  "$F_TRANSFER" "$T_TRANSFER" "$NEW_SDK" \
  --qa "$QA_HEAD" --run "$SOURCE_RUN" --attempt 1 --manifest "$MANIFEST_SHA256"
```
