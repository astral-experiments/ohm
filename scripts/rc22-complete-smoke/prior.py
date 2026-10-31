"""Authenticate the three completed earlier outer shells and the one nonportable GNU QA Cargo."""

import gzip
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, REPO, locations, need, save, sha

RUN = 41249054242
HEAD = "b029efc9d462e47b8d62256a986b14644da40c1c"
REF = "charlie/qa-rc22-complete-input-smoke-20261031"
SPEC = {
    "x86_64-unknown-linux-gnu": (
        124678526470,
        13060915717,
        50171,
        "a47ed6db8ca1291d3753415a79da9c4744d8941cb7f54234b5bf369dc495273f",
    ),
    "aarch64-apple-darwin": (
        124678526252,
        13060985236,
        60741,
        "984128cb19b8f77352b18d57664e04985f3f68db4777a2c5cfceb5f63b45c1be",
    ),
}


def project(archive, target):
    job, aid, size, digest = SPEC[target]
    need(archive.stat().st_size == size and sha(archive) == digest, "wrong first official QA ZIP")
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist()) == len(set(z.namelist())), "duplicate previous member")
        read = lambda n: json.loads(z.read(n))
        binding = read("enrollment.json")
        need(
            binding["OHM_QA_TARGET"] == target
            and binding["GITHUB_SHA"] == HEAD
            and binding["GITHUB_RUN_ID"] == str(RUN)
            and binding["GITHUB_REF"] == "refs/heads/" + REF,
            "wrong first run enrollment",
        )
        result = {}
        for role in ("packaged", "fourfix"):
            prefix = role + "/full/"
            get = lambda n: read(prefix + n)
            need(
                read(role + "/outcome.json") == {"role": role, "statuses": {"full": 1}}
                and get("terminal.json") == {"exit": 1, "observed_link_gate_failure": False},
                "incorrect prior refusal",
            )
            err = gzip.decompress(z.read(prefix + "stderr.log.gz")).decode()
            complete = prefix + "release-shell.exit" in z.namelist()
            if target.startswith("x86_64") and role == "fourfix":
                stdout = gzip.decompress(z.read(prefix + "stdout.log.gz")).decode()
                need(
                    not complete
                    and "Cargo links against nonportable native libraries" in err
                    and "libz.so.1 => " in stdout,
                    "lost old portability veto",
                )
            else:
                need(
                    complete
                    and z.read(prefix + "release-shell.exit") == b"0\n"
                    and "workspace did not reuse real expected registry artifact" in err,
                    "different first full shell",
                )
                rows = get("worktree-commands.json")
                last = rows[-1]
                need(
                    last["status"] == 0 and last["argv"][:3] == ["cargo", "+" + CFG["release"], "build"],
                    "different prior worktree",
                )
                (itoa,) = [
                    r
                    for r in map(json.loads, last["stdout"].splitlines())
                    if r.get("target", {}).get("name") == "itoa"
                ]
                raw = gzip.decompress(z.read(prefix + "stdout.log.gz")).decode()
                parent_paths = {
                    q
                    for l in raw.splitlines()
                    if " --crate-name itoa " in l
                    for q in re.findall(r" --out-dir ([^ ]+)", l)
                }
                need(
                    len(parent_paths) == 1 and any("/registries/" in q for q in parent_paths),
                    "incorrect prior parent",
                )
                namespace = "/registries/" if target.startswith("x86_64") else "/workspaces/"
                need(
                    not itoa["fresh"]
                    and all(
                        namespace in f and str(Path(f).parent) not in parent_paths for f in itoa["filenames"]
                    ),
                    "changed prior negative",
                )
            result[role] = {"outer_exit": 0 if complete else 1, "whole_arm": 1}
        return {"run": RUN, "head": HEAD, "job": job, "artifact": aid, "zip_sha256": digest, "roles": result}


def main():
    root, target = locations()
    job, aid, size, digest = SPEC[target]
    prefix = ["gh", "api", "repos/" + REPO + "/actions/"]

    def cli(s):
        return prefix[:2] + [prefix[2] + s]

    run, j, a = [
        json.loads(subprocess.check_output(cli(endpoint)))
        for endpoint in [f"runs/{RUN}", f"jobs/{job}", f"artifacts/{aid}"]
    ]
    need(
        run["id"] == j["run_id"] == a["workflow_run"]["id"] == RUN
        and run["head_sha"] == j["head_sha"] == a["workflow_run"]["head_sha"] == HEAD
        and run["run_attempt"] == j["run_attempt"] == 1
        and run["path"] == ".github/workflows/ci.yml"
        and run["head_branch"] == REF
        and run["event"] == "workflow_dispatch"
        and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO
        and run["conclusion"] == j["conclusion"] == "failure"
        and j["id"] == job
        and j["name"] == "Complete smoke (" + target + ")"
        and any(
            s["name"] == "Retain original, partial, or complete QA receipts only"
            and s["conclusion"] == "success"
            for s in j["steps"]
        )
        and a["id"] == aid
        and a["size_in_bytes"] == size
        and a["digest"] == "sha256:" + digest
        and not a["expired"],
        "wrong real previous QA",
    )
    archive = root / "receipts/previous-qa.zip"
    b = subprocess.check_output(cli(f"artifacts/{aid}/zip"))
    need(len(b) == size and hashlib.sha256(b).hexdigest() == digest, "wrong previous QA bytes")
    archive.write_bytes(b)
    save(root / "receipts/previous-qa.json", project(archive, target))


if __name__ == "__main__":
    main()
