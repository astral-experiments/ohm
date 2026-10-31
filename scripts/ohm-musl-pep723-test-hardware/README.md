# Reproduce the offline admission checks

The 22 real structural test builds used both complete Ruff revisions and are available from the original run. This separate packet contains a prospective two-position hardware acquisition and an independent reader. It contains **zero newly measured instruction counts**. [Original structural run](https://github.com/astral-experiments/ohm/actions/runs/41174368146)

The offline test uses Python 3.11+ on Linux, Git, three checkouts of the public Ohm packaging repository, the original 4.2 MB structural ZIP, and the two prior official visitor calibration ZIPs. Supply original downloaded ZIPs without extracting or repacking them. Each archive is authenticated before a member is used. The calibration ZIPs must be named 01.zip and 02.zip, in position order. selfcheck.py opens only their successful calibration members. Its artificial clock values and synthetic syscall topologies verify the reader and never enter a scientific result. [Old calibration ZIPs](https://github.com/astral-experiments/ohm/actions/runs/41173700698)

From this directory, set STRUCTURAL to a checkout at 58aad7854096055e3b1b8ea4a42dc231fa46e92b, HARDWARE to one at 5d6abc7cf533b1a85264c18525c9f8917aeb47d3, QUALIFICATION to a readable Git checkout containing 89a055549f4335e6e172f96c65d162dcd9cb1046, ORIGINAL to artifact 13031454493, and CALIBRATION to the directory containing the two old calibration ZIPs.

    sha256sum --strict --check SHA256SUMS
    python3 -IB selfcheck.py --original "$ORIGINAL" --structural "$STRUCTURAL" \
      --hardware "$HARDWARE" --qual-donor "$QUALIFICATION" --calibration "$CALIBRATION"

The output should match offline-check.json. The checks verify all 451 earlier structural members, replay all four historical test-build argument sets through the stronger reader with synthetic process trees, try corrupting the driver, linker, process ancestry, thread exits and role order, and verify the 56 previously observed calibration commands. They execute no new Ruff, PMU or hosted commands.

The held workflow template expects this packet under scripts/ohm-musl-pep723-test-hardware and a copy of workflow.yml under .github/workflows. Any later authorized QA ref must bind receipt IDs and hashes in clearance.json and its literal SHA-256 in permit.json, and reseal that data-only enrollment. Keep this original sealed packet intact. Run stage.py, worker.py and score.py with -IB and without Python optimization. For a future accepted pair, obtain both original official job ZIPs and the digests independently from Actions, then run:

    python3 -IB score.py --structural-zip "$ORIGINAL" \
      "$POSITION1_ZIP" "$POSITION1_OFFICIAL_SHA256" \
      "$POSITION2_ZIP" "$POSITION2_OFFICIAL_SHA256"

The worker deliberately preserves a partial packet on failure. The independent reader will score only two complete, authorized positions with all native, counter and storage gates. PLAN.md identifies the precise endpoints and the previously unclassified cold trace attachment. The original packages and compiled SDKs are referenced by SHA-256 and artifact IDs in registration.json.
