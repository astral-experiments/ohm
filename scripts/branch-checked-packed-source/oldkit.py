"""Reopen both genuine old-E artifacts before allowing that compiler to write shared sessions."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corrected
import locate_e

ORIGIN = corrected.ORIGINAL_ARTIFACT
need, sha = corrected.need, corrected.reg.sha


def verify(inbox, capsule=None):
    official = {k: v for k, v in ORIGIN.items() if k != "qualified"}
    need(
        locate_e.media(official, inbox) == ORIGIN["qualified"],
        "different old-E native/SDK qualification",
    )
    if capsule is None:
        return official
    capsule.mkdir()
    with zipfile.ZipFile(inbox / "first-session-linux-source-driver.zip") as z:
        raw = z.read("manifest.json")
        m = json.loads(raw)
        for name, subject in {
            "manifest.json": (ORIGIN["qualified"]["manifest"], len(raw)),
            **m["products"],
        }.items():
            need(
                name in {"manifest.json", "E-delta.tar.zst"}
                and 0 < z.getinfo(name).file_size == subject[1] < 128 * 2**20,
                "unbounded original member",
            )
            with z.open(name) as src, (capsule / name).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            need(sha(capsule / name) == subject[0], "wrong original member")
    return official


def fetch(inbox, cli):
    r = ORIGIN["run"]

    def api(suffix):
        return json.loads(
            subprocess.check_output(
                [cli, "api", f"repos/{corrected.reg.REPO}/actions/runs/{r}" + suffix]
            )
        )

    o = locate_e.check(
        r, ORIGIN["head"], api(""), api("/attempts/1/jobs")["jobs"], api("/artifacts")["artifacts"]
    )
    need(
        o == {k: v for k, v in ORIGIN.items() if k != "qualified"},
        "old E came from another official job",
    )
    inbox.mkdir()
    for name, a in o["artifacts"].items():
        argv = [cli, "api", f"repos/{corrected.reg.REPO}/actions/artifacts/{a['id']}/zip"]
        with subprocess.Popen(argv, stdout=subprocess.PIPE) as p, (inbox / (name + ".zip")).open(
            "xb"
        ) as target:
            with p.stdout as stream:
                total = 0
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    total += len(chunk)
                    if total > a["size_in_bytes"]:
                        p.kill()
                        raise RuntimeError("excess original artifact bytes")
                    target.write(chunk)
            need(total == a["size_in_bytes"] and p.wait() == 0, "incomplete original artifact")
    verify(inbox)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("verify", "fetch"))
    p.add_argument("inbox", type=Path)
    p.add_argument("--gh", default="gh")
    a = p.parse_args()
    if a.action == "verify":
        print(json.dumps(verify(a.inbox), sort_keys=True))
    else:
        fetch(a.inbox, a.gh)
