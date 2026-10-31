"""Enroll the two already-downloaded official ZIPs after a real terminal native-source qualification."""

import argparse
import copy
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingress import (
    NATIVE_ARCHIVES,
    digest,
    members,
    need,
    official,
    one,
    registration,
    run_header,
    sha,
)


def main(args):
    r = copy.deepcopy(registration("inspect"))
    s = r["source"]
    need(s and s["run"] not in [g["run"] for g in r["excluded_source_runs"]], "wrong or excluded native run")
    run_header(s)
    got = official("runs/" + str(s["run"]) + "/artifacts?per_page=100")
    need(
        got["total_count"] == len(got["artifacts"]) == len(NATIVE_ARCHIVES)
        and {x["name"] for x in got["artifacts"]} == NATIVE_ARCHIVES,
        "not the pair of official native originals",
    )
    submitted = {
        "gnu-renderer-qualified-native": args.kit,
        "gnu-renderer-source-native-observations": args.logs,
    }
    s["artifacts"] = {}
    for row in got["artifacts"]:
        p = submitted[row["name"]]
        h = sha(p)
        need(
            not row["expired"]
            and row["workflow_run"]["id"] == s["run"]
            and row["workflow_run"]["head_sha"] == s["head"]
            and row["digest"] == "sha256:" + h
            and row["size_in_bytes"] == p.stat().st_size,
            "wrong concrete source original",
        )
        s["artifacts"][row["name"]] = {"id": row["id"], "bytes": p.stat().st_size, "sha256": h}
    with zipfile.ZipFile(args.kit) as z:
        s["manifest_sha256"] = digest(z.read(one(z, "manifest.json")))
    with tempfile.TemporaryDirectory(dir=args.scratch) as private:
        root = Path(private)
        path = "scripts/gnu-renderer-cgu-source"
        arc = subprocess.check_output(
            ["git", "-C", args.checkout, "archive", "--format=tar", s["head"], "--", path]
        )
        with tarfile.open(fileobj=io.BytesIO(arc)) as t:
            t.extractall(root, filter="data")
        code = root / path
        mf = members(r, code, args.kit, args.logs, root / "transfer")
        import restore

        # Reopen full original P plus two complete physically separate role views. Each member's digest,
        # length and mode are checked in the released source-run restore before any entry is executable.
        for role in "PFC":
            sdk = root / role
            detail = restore.restore(root / "transfer", sdk, role, s["head"], s["run"], 1)
            expected = sha(sdk / mf["driver"])
            need(expected == detail["driver"][0], "wrong installed driver " + role)
            import shutil

            shutil.rmtree(sdk)
    result = {"source": s, "independently_reopened": mf}
    with args.out.open("x") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("kit", "logs", "checkout", "scratch", "out"):
        p.add_argument("--" + k, type=Path, required=True)
    main(p.parse_args())
