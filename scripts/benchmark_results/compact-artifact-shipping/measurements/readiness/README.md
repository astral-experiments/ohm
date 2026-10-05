# Reproduce the four-round receipt audit

Run from `scripts/benchmark_results/compact-artifact-shipping/` in this
repository. Python and tar are sufficient; the audit uses recorded source,
commands, logs, and hashes, without running compilers or requiring credentials.
Allow about 1 GiB for extraction. The original compiler binaries, build trees,
and filesystem images are not distributed in these archives.

The two archives extract into one `readiness-proof/` directory with no overlapping
file members. The first is the unchanged source/correctness bundle; the second
adds the full interrupted and continued measurement evidence. These commands
use a fresh temporary directory and verify both inventories before auditing:

```sh
compact_proof_dir="$(mktemp -d)"
tar -xzf correctness/readiness/current-cut-correctness.tar.gz -C "$compact_proof_dir"
tar -xzf measurements/readiness/readiness-matrix.tar.gz -C "$compact_proof_dir"
python3 - "$compact_proof_dir/readiness-proof" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
for name in ("inventory.json", "matrix-inventory.json"):
    inventory = json.loads((root / name).read_text())
    records = inventory["files"]
    assert len(records) == inventory["file_count"]
    assert sum(r["bytes"] for r in records) == inventory["total_bytes"]
    for record in records:
        relative = Path(record["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        file = root / relative
        assert file.is_file() and not file.is_symlink(), file
        assert file.stat().st_size == record["bytes"], file
        assert hashlib.sha256(file.read_bytes()).hexdigest() == record["sha256"], file
    print(name, len(records), "payload files verified")
PY
PYTHONDONTWRITEBYTECODE=1 python3 \
  "$compact_proof_dir/readiness-proof/readiness/matrix/harness/audit_readiness_continued.py" \
  "$compact_proof_dir/readiness-proof/readiness/evidence" \
  --original-build "$compact_proof_dir/readiness-proof/provenance/original-compiler-build.json" \
  --harness "$compact_proof_dir/readiness-proof/readiness/harness/benchmark_readiness_v2.py" \
  --continuation-harness "$compact_proof_dir/readiness-proof/readiness/harness/benchmark_readiness_continuation.py" \
  --continuation-plan "$compact_proof_dir/readiness-proof/readiness/harness/continuation-plan.json" \
  --source-snapshots "$compact_proof_dir/readiness-proof/readiness/evidence/fixture-originals" \
  --summary "$compact_proof_dir/readiness-proof/readiness/matrix/readiness-summary.json" \
  --output "$compact_proof_dir/independent-audit.json"
```

The expected result is `passed: true`, 416 primary commands, 443 raw commands,
and 73,105 portable checks. The audit reconstructs the primary selection and
recomputes all 70 comparison groups from the raw rows, including each round.
It checks fixtures, runtime oracles, no-op identities, format guards, resource
admission, and build/measurement provenance. The three sequential edits within
each round remain dependent observations.

The original 81,113-check audit also verified all 2,669 files in the devbox
transfer. This portable invocation omits that transfer-manifest check: five
cache bookkeeping files totaling 44 bytes were explicitly excluded from the
sealed static bundle. Their paths, lengths, hashes, and reasons remain in
`matrix-inventory.json` under `retained_static_exclusions`. No measurement,
oracle, failure, or selection receipt is omitted. The [independent extraction
receipt](portable-review.json) verifies both inventories and confirms that the
portable audit reproduces the original summary, selection, and comparisons.

The static bundle's original README describes a prospective uninterrupted
matrix. This guide replaces that recipe for the actual interrupted/continued
study; neither sealed archive has been modified to rewrite its history.

Archive SHA-256 identities:

- `current-cut-correctness.tar.gz`: `3da176a3a30003bbd2a771f2dd31afa2544a4000097964df32be70a0a58dd986`
- `readiness-matrix.tar.gz`: `9832541221286816eac2055ae93c47c0b2811d0e83cc6dcd39ee7b561e3261a6`
