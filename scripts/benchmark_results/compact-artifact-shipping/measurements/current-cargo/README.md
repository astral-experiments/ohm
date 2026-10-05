This supplement contains the actual Cargo `6333daf7` Linux integration proof and its separate 156-command timing confirmation: two fresh forward/reverse rounds, two projects, and baseline/ordinary/compact arms. It is not pooled with the earlier four-round Cargo `4a2813050` study. The compiler and Wild binaries retain their recorded identities; the published Rust update changes only its Cargo gitlink.

The independent audit passed **28,855 checks**, including all **870 current transferred files** and **42 comparison groups**. The installed default/compact executable, library, proc-macro and removed-option proof separately passed **167 audit checks**. These are audits of recorded executions and bytes, not fresh compiler or benchmark runs.

The archives form three non-overlapping layers under `readiness-proof/`. The supplied verifier pins each compressed archive and embedded inventory, validates every regular member's size and SHA-256, rejects unsafe paths, links, duplicate members and cross-archive overlaps, and uses exclusive file creation in a new directory.

| Layer | Archive | SHA-256 | Regular archive files | Inventory payload entries |
| --- | --- | --- | ---: | ---: |
| Compiler correctness | `correctness/readiness/current-cut-correctness.tar.gz` | `3da176a3a30003bbd2a771f2dd31afa2544a4000097964df32be70a0a58dd986` | 391 | 390 |
| Original four-round study | `measurements/readiness/readiness-matrix.tar.gz` | `9832541221286816eac2055ae93c47c0b2811d0e83cc6dcd39ee7b561e3261a6` | 2,391 | 2,390 |
| Current Cargo confirmation | `measurements/current-cargo/current-cargo-evidence.tar.gz` | `7a3456f006a8903d59349f28cec8c6c8555542a35b458e755c3e4db10d97355b` | 917 | 916 |

Each archive has one inventory in addition to its payload entries. The combined extraction contains **3,699 regular files**, with **zero overwrites**. The archives contain no directory members; extraction creates the needed directories. The current supplement is 31,833,060 compressed bytes and 361,051,102 uncompressed bytes, including its inventory. Allow at least 2 GiB free for all three layers.

Run the following from `scripts/benchmark_results/compact-artifact-shipping/` with Python 3.11 or newer. The fresh directory must not already contain a `layers/` directory. All three inventories and the no-overwrite contract are checked before a successful receipt is emitted.

```sh
repro_dir=$(mktemp -d "${TMPDIR:-/tmp}/ohm-current-cargo.XXXXXX")
python3 measurements/current-cargo/verify-archives.py \
  --correctness correctness/readiness/current-cut-correctness.tar.gz \
  --matrix measurements/readiness/readiness-matrix.tar.gz \
  --current measurements/current-cargo/current-cargo-evidence.tar.gz \
  --destination "$repro_dir/layers" \
  --receipt "$repro_dir/inventories.json"
proof="$repro_dir/layers/readiness-proof"
```

Reproduce the actual current-Cargo native proof audit:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  "$proof/readiness/current-confirmation/harness/audit_current_cargo.py" \
  "$proof" \
  --output "$repro_dir/native-audit.json"
```

Then reproduce the frozen `6a19dcdc…` timing auditor, including the complete current transfer manifest. All 870 current files are present across the three layers. The documented 44-byte exclusion from the older archive applies only to that older transfer; it is not an exclusion from this current audit.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  "$proof/readiness/current-confirmation/harness/audit_current_confirmation.py" \
  "$proof/readiness/evidence" \
  --original-build "$proof/provenance/original-compiler-build.json" \
  --current-cargo-receipt "$proof/readiness/final-cargo-current/evidence/result.json" \
  --prior-primary-audit "$proof/readiness/final-cargo-current/independent-matrix-audit.json" \
  --prior-collection "$proof/readiness/evidence/collection.json" \
  --harness "$proof/readiness/harness/benchmark_current_cargo.py" \
  --source-snapshots "$proof/readiness/evidence/fixture-originals" \
  --summary "$proof/readiness/current-confirmation/readiness-summary.json" \
  --transfer-manifest "$proof/readiness/evidence/current-cargo-collection.json" \
  --transfer-root "$proof" \
  --output "$repro_dir/current-audit.json"
```

The commands were tested against a fresh combined extraction. The native and timing audits reproduce the retained actual receipts byte-for-byte: native audit SHA-256 `c7cee3f283cf37653cabf410f6a972bd19f7ce90ca99543c403462028f82f4c1` and timing audit `557577d89bde0e2ccd247c6ecd1b9d648308304f01a8eb8c16456168186b36e0`. See `portable-reproduction.json` for the archive identities, inventory counts and audit results.

Raw rows, command logs, source-copy manifests, runtime-oracle checks, source reviews, preservation receipts and the exact audited summary are retained inside the archives. The original interrupted 339-row study and its failed final command remain preserved in the earlier layer; the current 156-command confirmation has no rejected or excluded rows. No original build checkout or devbox access is required for these evidence audits.
