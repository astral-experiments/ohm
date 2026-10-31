# Replay the direct whole-Ruff storage comparison

The experiment compares the disabled default and the enabled branch cache on the same F compiler with the enabled cache on E. Each worker runs the 375-unit Ruff CLI from empty, across a real branch switch, back in both directions, through an untouched build, and through an invalid edit and repair. An independent history inserts the upstream parser fix #28233 and its repeat before the first switch. The two histories, both allocation lanes, raw counters, physical sources and correctness rules are pinned in [the registration](PLAN.md).

F was built at `c6fe8ecda65452c105f85367a009af80cbb5efbc`. F, `f7061203` and #274’s rebased `6dbcba66` have identical compiler, library and tests trees. The new enrollment uses corrected E `393b4b05a4bfa3f531a36023846f86236a6b71a9`, whose native source qualification runs separately. The carrier requires the independently reproduced raw/packed conflict and genuine mixed-writer receipts. It restores both 81-member SDKs and requires the compiler driver and matching rustdoc to be the only differences. The same strict Cargo and signed Wild run in every role. [Source addendum](SOURCE-ADDENDUM.md)

## Before enrollment

Run these commands from the dedicated, clean packaging checkout. The first verifies the entire confirmation subtree. The tests check both inclusive storage thresholds and the strict CPU thresholds, all six orders, the twelve-worker requirement, historical boot reuse, raw counter scheduling, historical official ZIP identities, changed/missing native controls and the exact five-interval coverage.

```sh
Q=scripts/branch-storage-e-confirmation
(cd "$Q" && sha256sum --strict --check --status SHA256SUMS)
python3 -IB "$Q/test_confirm.py" -v
python3 -IB "$Q/test_checked_source.py"
python3 -IB scripts/branch-first-session-e-screen/test_metrics.py
python3 -IB scripts/branch-first-session-e-screen/test_screen.py
```

The earlier-source fixtures in `review/fixtures` preserve the authenticated reference data used in preflight. Prior Eon from the E pilot and prior Foff and Fon from the T pilot cover 66 normal/metered commands, nine independent empty references, real returned Ruff and typed-reader binaries, and all three mutable-provider histories. These workers belong to two different prior studies. Their outcomes only exercise the reader and project the expected range. All twelve confirmation pairs will be new.

On the shared devbox, the following commands re-execute those originals in place. Native ELF execution from a Linux memfd must be available. Keep the calibration Git objects at the named revision and the worker-calibration checkout physically at its enrolled HEAD `8a659140`.

```sh
OSS=/home/dev-user/code/oss
SAFE=/mnt/devbox-scratch/dev-user
CA="$OSS/ohm-package-qa-gnu-renderer-pfc-hardware-20261031"
OB="$OSS/ohm-package-qa-gnu-renderer-library-workers-20261031"
E1="$SAFE/ohm-branch-first-session-screen-41228642029/41228642029-01-13053879880.zip"
T1="$SAFE/ohm-branch-first-session-T-ordinary-41233336079/41233336079-01-13056276661.zip"
python3 -IB "$Q/review/test_flanks.py" --e-zip "$E1" --t-zip "$T1" \
  --ruff "$OSS/ruff" --calibration "$CA" --observer "$OB" | cmp - "$Q/review/fixtures/prior-flanks.json"
python3 -IB "$Q/review/test_mutations.py" "$E1" "$OSS/ruff" | cmp - "$Q/review/fixtures/original-mutations.json"
```

An archived control rehashed both 81-file F and historical E toolchains, switched their five role activations at one pathname and opened Cargo each time. Its E predates the raw/packed correction. The corrected source-only gate separately requires 76 physical compiler visits and the 16 genuine Wild archive reads, including the earlier-provider, same-stat and malformed cases. The ordinary E and T registrations each bind two complete worker archives. Each original worker includes nine independently empty references. The independent corrected-source ingress physically rehashed both restored 81-file SDKs and opened Cargo on Foff, Fon, Eon, Fon and Foff at the same path. All 81 transfer-ready SDK inodes stayed separate and their ctimes stayed unchanged. `review/fixtures/checked-source-ingress.json` contains those receipts. `inputs/pilots.json`, `review/fixtures/native-f-e-source-only.json` and `review/fixtures/previous-studies.json` preserve the earlier controls.

## Exclude previous workers

The small registration already holds the 54 earlier storage/CLI, source, E and T boot identities. The following command opens the twelve original ZIPs of the distinct full-Cargo integration confirmation at `41235234268`, validates their raw boot IDs and native receipts, and writes two new JSON files to an empty directory. The archive inputs remain in place. The completed 66-boot union is bound to the original ZIP identities, including all twelve F integration workers.

```sh
python3 -IB "$Q/seal_boots.py" \
  "$SAFE/ohm-ruff-integration-f-confirmation-originals-20261031" \
  "$HOME/.cache/ohm-ruff-integration-f-confirmation-reader-20261031-v1/results" \
  "$HOME/.cache/ohm-branch-storage-e-confirmation-20261031/verified-f-integration-41235234268"
```

After independent review, the exact prepared QA head can run `.github/workflows/ci.yml` on `charlie/qa-branch-storage-checked-confirmation-20261031` once with `reviewed_head` set to that full SHA. The first job verifies the four prior pilot ZIPs and all twelve integration originals against the official API. The twelve native workers use the six frozen role orders twice, with maximum parallelism four and 355 minutes per worker. Each worker requires 32 GiB before admission. The offline replay requires the full official sizes plus a 4 GiB volume reserve. The two prior pilots took approximately 52 minutes per worker and had about 362–364 MB per original.

## Reopen a finished confirmation

Set `RUN` and `HEAD` to the new, reviewed, completed first attempt and prepare an empty private destination. The native reader first verifies all twelve official ZIPs, boot IDs, SDKs, calibrations, all 396 separately run ordinary commands, 108 empty references and 36 mutable-provider panels. Only then does it read the 396 metered commands and compute the five intervals. A failed original can be collected and inspected. The scored replay requires every enrolled original to succeed.

```sh
: "${RUN:?set to the official new run}" "${HEAD:?set to the full reviewed SHA}"
test "$(git rev-parse HEAD)" = "$HEAD"
MEDIA="$SAFE/ohm-branch-storage-e-confirmation-$RUN"
mkdir -p -m 700 "$MEDIA"
python3 -IB "$Q/review/replay.py" collect --run "$RUN" --head "$HEAD" \
  --media "$MEDIA" --catalog "$MEDIA/official.json"
python3 -IB "$Q/review/replay.py" replay --run "$RUN" --head "$HEAD" \
  --media "$MEDIA" --catalog "$MEDIA/official.json" \
  --f-sdk "$SAFE/ohm-branch-return-native-41199659076/branch-return-source-sdk.zip" \
  --e-sdk "$SAFE/ohm-branch-checked-packed-source-41242910474/first-session-linux-source-driver.zip" \
  --ruff "$OSS/ruff" --observer "$OB" --calibration "$CA" --out "$MEDIA/full-result.json"
```

Report the real instruction and storage costs across all seven commands, the independent parser history, both return directions, unchanged and repair. The reader includes the largest post-command allocation by role and history. Shared runner storage cannot identify a peak during compilation. On an exclusive calibrated filesystem, retain the separately sampled maximum and sampling gap. Reopen every source/ELF/roster or allocation discrepancy from its original and retain the refusal.
