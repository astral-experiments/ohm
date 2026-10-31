"""Restore only the source-qualified corrected GNU SDK from its two original verified transfers."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corrected
import restore_e

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("K_transfer", "capsule", "destination"):
        p.add_argument(n, type=Path)
    for n in ("qa", "run", "attempt", "manifest"):
        p.add_argument("--" + n, required=True)
    a = p.parse_args()
    raw = a.capsule / "manifest.json"
    corrected.need(
        corrected.reg.sha(raw) == a.manifest and 0 < raw.stat().st_size < 256 << 10,
        "different candidate manifest",
    )
    m = json.loads(raw.read_bytes())
    corrected.need(
        re.fullmatch("[0-9a-f]{64}", m["collision"])
        and m["legacy_sdk"] == corrected.ORIGINAL_ARTIFACT["qualified"]["manifest"],
        "missing independently authenticated collision check",
    )
    print(
        json.dumps(
            restore_e.restore(
                a.K_transfer,
                a.capsule,
                a.destination,
                a.qa,
                a.run,
                a.attempt,
                a.manifest,
                authority=corrected,
            ),
            sort_keys=True,
        )
    )
