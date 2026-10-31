"""Restore a qualified E from the original K on a private staging path, verifying the complete SDK."""

import argparse
import json
from pathlib import Path
import re
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject
import restore as base
from registration import need, sha


def differences(k, files):
    previous = k["files"]["K"]
    need(set(files) == set(previous) and len(files) == 81, "different installed SDK paths")
    driver = k["driver"]
    changed = {}
    for name, current in files.items():
        old = previous[name]
        if current != old:
            need(
                name in {driver, "bin/rustdoc"}
                and len(current) == 3
                and re.fullmatch("[0-9a-f]{64}", current[0])
                and current[0] != old[0]
                and 0 < current[1] < 512 * 2**20
                and current[2] == old[2],
                "unexpected native member " + name,
            )
            changed[name] = current
    need(driver in changed, "compiler driver did not change")
    return changed


def restore(ktransfer, capsule, dest, qa, run, attempt, digest):
    candidate = subject.load()
    origin = subject.K_ORIGIN
    need(
        set(p.name for p in capsule.iterdir()) == {"manifest.json", "E-delta.tar.zst"}
        and all(p.is_file() and not p.is_symlink() for p in capsule.iterdir()),
        "foreign source capsule",
    )
    raw = capsule / "manifest.json"
    need(raw.stat().st_size <= 256 * 1024 and sha(raw) == digest, "unauthenticated E manifest")
    m = json.loads(raw.read_bytes())
    need(
        m["qualified"] is True
        and m["source"] == candidate
        and m["base"] == origin
        and (m["qa"], m["run"], m["attempt"]) == (qa, str(run), "1")
        and str(attempt) == "1"
        and m["host"] == subject.reg.HOST,
        "different E source qualification",
    )
    kpath = ktransfer / "manifest.json"
    need(sha(kpath) == origin["manifest"], "unverified original K")
    k = json.loads(kpath.read_bytes())
    changed = differences(k, m["files"])
    need(
        m["delta"] == sorted(changed)
        and m["driver"] == k["driver"]
        and m["stage0"] == k["stage0"]
        and m["llvm"] == k["llvm"],
        "candidate/bootstrap disagreement",
    )
    delta = capsule / "E-delta.tar.zst"
    need(
        set(m["products"]) == {delta.name}
        and 0 < delta.stat().st_size < 256 * 2**20
        and m["products"][delta.name] == [sha(delta), delta.stat().st_size],
        "corrupt E payload",
    )
    need(not dest.exists() and not dest.is_symlink(), "new unrelated output directory required")
    with tempfile.TemporaryDirectory(prefix=".e-restore-", dir=dest.parent) as tmp:
        sdk = Path(tmp) / "sdk"
        base.restore(ktransfer, sdk, "K", origin["head"], str(origin["run"]), "1", origin["manifest"])
        base.extract(delta, sdk, changed, True)
        actual = {}
        for p in sdk.rglob("*"):
            need(not p.is_symlink() and (p.is_dir() or p.is_file()), "unexpected installed file type")
            if p.is_file():
                st = p.stat()
                actual[str(p.relative_to(sdk))] = [sha(p), st.st_size, stat.S_IMODE(st.st_mode)]
        need(actual == m["files"], "installed E differs")
        sdk.rename(dest)
    return {
        "role": "E",
        "commit": candidate["role"]["commit"],
        "manifest": digest,
        "driver": actual[m["driver"]],
        "rustdoc": actual["bin/rustdoc"],
        "cargo": actual["bin/cargo"],
        "wild": actual[subject.reg.WILD],
        "members": len(actual),
        "changed": sorted(changed),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("k_transfer", "e_capsule", "destination"):
        p.add_argument(name, type=Path)
    for name in ("qa", "run", "attempt", "manifest"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    print(
        json.dumps(
            restore(a.k_transfer, a.e_capsule, a.destination, a.qa, a.run, a.attempt, a.manifest),
            sort_keys=True,
        )
    )
