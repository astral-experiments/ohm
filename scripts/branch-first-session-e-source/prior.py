"""Reopen the exact supported old K output and its independently successful test observations."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject as s
import locate
import restore as old
from registration import need, sha


def fetch(inbox):
    o = s.K_ORIGIN
    result = locate.locate(o["run"], o["head"], "gh")
    need(
        result["job"] == 124532776606
        and result["attempt"] == 1
        and result["artifacts"]
        == {k: [r["id"], r["size"], r["sha256"]] for k, r in o["artifacts"].items()},
        "wrong original source or official artifact",
    )
    inbox.mkdir()
    for name, row in o["artifacts"].items():
        with (inbox / (name + ".zip")).open("xb") as target:
            subprocess.run(
                ["gh", "api", f"repos/astral-experiments/ohm/actions/artifacts/{row['id']}/zip"],
                stdout=target,
                check=True,
            )


def reopen(inbox, transfer=None):
    s.inherited()
    o = s.K_ORIGIN
    files = {}
    for n, row in o["artifacts"].items():
        p = inbox / (n + ".zip")
        need(
            not p.is_symlink()
            and p.is_file()
            and p.stat().st_size == row["size"]
            and sha(p) == row["sha256"],
            "wrong original " + n,
        )
        files[n] = p
    with zipfile.ZipFile(files["branch-return-source-sdk"]) as z:
        need(
            set(z.namelist()) == {"manifest.json", "K-delta.tar.zst", "F-sdk.tar.zst"}
            and len(z.infolist()) == 3,
            "unrecognized original native media",
        )
        raw = z.read("manifest.json")
        need(hashlib.sha256(raw).hexdigest() == o["manifest"], "different original K SDK")
        m = json.loads(raw)
        if transfer:
            transfer.mkdir()
            for key in z.namelist():
                want = m["products"][key] if key != "manifest.json" else [o["manifest"], len(raw)]
                need(
                    z.getinfo(key).file_size == want[1] and want[1] <= 256 * 2**20, "unbounded K member"
                )
                with z.open(key) as source, (transfer / key).open("xb") as target:
                    shutil.copyfileobj(source, target, 1 << 20)
                need(sha(transfer / key) == want[0], "changed K source payload")
    with zipfile.ZipFile(files["branch-return-source-observations"]) as z:
        get = lambda f: json.loads(z.read("receipts/" + f))
        final = get("qualified.json")
        tests = get("K/checked-in-tests.json")
        native = get("K/native-shadow/complete.json")
        need(
            final["manifest"] == o["manifest"]
            and final["roles"]["K"] == m["roles"]["K"] == s.reg.SOURCE()["roles"]["K"]
            and m["files"]["K"] == get("K/before-tests.json") == get("K/inventory.json"),
            "different original tested SDK",
        )
        need(
            hashlib.sha256(z.read("receipts/K/checked-in-tests.json")).hexdigest() == m["tests"]["K"]
            and len(tests["unit"]) == 10
            and len(tests["run_make"]) == 7,
            "missing original tests",
        )
        need(
            native["physical_cargo"] == s.reg.ELF
            and native["physical_wild"] == s.reg.WILD_SHA
            and native["visits"] == 16
            and m["files"]["K"][m["driver"]][0]
            == "72f0f62adf9c301a87c2db3427b097bab60bfb3857caa84123489f69d339f9fa"
            and len(m["files"]["K"]) == 81,
            "wrong operational K",
        )
        return m, tests, get("K/bootstrap.command.json"), get("K/unit-platforms.json")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "fetch":
        raise SystemExit("prior.py fetch NEW_INBOX")
    fetch(Path(sys.argv[2]))
