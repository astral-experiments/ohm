"""Return the verified official ZIP identities of one successful E qualification, for independent download."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject as s
import read_cross
import selector_record

NAME = "Exact E source, Rust regressions and native providers"
STEPS = (
    "Refuse missing or foreign product registration before acquiring inputs",
    "Reopen the original successful K source job and its two artifacts",
    "Build only E and qualify its checked-in tests and real native providers",
    "Publish the qualified Linux driver capsule",
    "Preserve source and native observations",
)


def check(run, sha, entry, jobs, artifacts):
    s.need(
        (
            entry["id"],
            entry["head_sha"],
            entry["head_branch"],
            entry["run_attempt"],
            entry["event"],
            entry["path"],
            entry["conclusion"],
        )
        == (
            run,
            sha,
            s.REF.removeprefix("refs/heads/"),
            1,
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "success",
        ),
        "wrong or incomplete official workflow",
    )
    (job,) = jobs
    s.need(
        (job["name"], job["head_sha"], job["run_attempt"], job["status"], job["conclusion"])
        == (NAME, sha, 1, "completed", "success"),
        "incorrect actual native worker",
    )
    for name in STEPS:
        (step,) = [r for r in job["steps"] if r["name"] == name]
        s.need(step["conclusion"] == "success", "unqualified " + name)
    names = {"first-session-linux-source-driver", "first-session-linux-source-observations"}
    s.need(len(artifacts) == 2 and {x["name"] for x in artifacts} == names, "wrong official E media")
    out = {}
    for a in artifacts:
        s.need(
            not a["expired"]
            and (a["workflow_run"]["id"], a["workflow_run"]["head_sha"]) == (run, sha)
            and 0 < a["size_in_bytes"] <= 256 * 2**20
            and re.fullmatch(r"sha256:[0-9a-f]{64}", a["digest"]),
            "invalid official ZIP",
        )
        out[a["name"]] = {key: a[key] for key in ("id", "size_in_bytes", "digest")}
    return {"run": run, "head": sha, "attempt": 1, "job": job["id"], "artifacts": out}


def media(catalog, folder):
    """Read the authenticated capsule manifest only after its matching native observations pass."""
    archives = {}
    for name, row in catalog["artifacts"].items():
        path = folder / (name + ".zip")
        s.need(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == row["size_in_bytes"]
            and "sha256:" + s.sha(path) == row["digest"],
            "foreign official artifact " + name,
        )
        archives[name] = path
    with zipfile.ZipFile(archives["first-session-linux-source-driver"]) as z:
        s.need(
            len(z.infolist()) == 2
            and set(z.namelist()) == {"manifest.json", "E-delta.tar.zst"}
            and z.getinfo("manifest.json").file_size < 256 * 1024,
            "unexpected native capsule",
        )
        raw = z.read("manifest.json")
    digest = hashlib.sha256(raw).hexdigest()
    m = json.loads(raw)
    with zipfile.ZipFile(archives["first-session-linux-source-observations"]) as z:
        s.need(len(z.namelist()) == len(set(z.namelist())), "ambiguous native observations")

        def read(name):
            s.need(z.getinfo(name).file_size <= 8 * 2**20, "oversize native proof")
            return z.read(name)

        end = json.loads(read("qualified.json"))
        s.need(
            m["qualified"] is True
            and m["base"] == end["base"] == s.K_ORIGIN
            and m["source"] == s.load()
            and end["commit"] == m["source"]["role"]["commit"]
            and end["role"] == "E"
            and (m["qa"], m["run"], m["attempt"])
            == (catalog["head"], str(catalog["run"]), "1")
            == (end["qa"], end["run"], end["attempt"])
            and end["manifest"] == digest,
            "wrong source job",
        )
        base = json.loads(read("E/original-K.json"))["sdk"]
        s.need(
            base["commit"] == s.K and base["manifest"] == s.K_ORIGIN["manifest"], "wrong donor compiler"
        )
        selector = selector_record.verify(lambda n: read("E/selector/" + n))
        s.need(selector["source"] == m["source"]["role"]["commit"]
               and selector["driver_sha256"] == base["driver"][0]
               and selector["sdk_executable_sha256"] == m["files"]["bin/rustc"][0],
               "foreign native selector/driver")
        for name, key in (
            ("E/selector/result.json", "selector"),
            ("E/checked-in-tests.json", "tests"),
            ("E/native-shadow/complete.json", "native"),
            ("E/cross-readers/complete.json", "cross_readers"),
        ):
            s.need(hashlib.sha256(read(name)).hexdigest() == m[key] == end[key], "different " + key)
        cross = json.loads(read("E/cross-readers/complete.json"))
        ordered = [
            ("E-cold-A-to-K", "E", "K", "packed"),
            ("E-first-A-to-K", "E", "K", "packed"),
            ("K-first-A-to-E", "K", "E", "raw"),
            ("K-packed-A-to-E", "K", "E", "packed"),
        ]
        s.need(len(cross) == len(ordered), "incomplete cross-reader histories")
        for (label, digest, program), (expected, writer, reader, rep) in zip(
            cross, ordered, strict=True
        ):
            s.need(label == expected, "wrong compiler direction")
            raw_case = read("E/cross-readers/" + label + "/qualified.json")
            c = json.loads(raw_case)
            s.need(
                hashlib.sha256(raw_case).hexdigest() == digest
                and c["producer"] == writer
                and c["consumer"] == reader
                and c["representation"] == rep
                and c["immediate_cold_read"] is (label == "E-cold-A-to-K")
                and c["cold_representation"] == ("packed" if writer == "E" else "raw")
                and c["first_B_compiler"] == (reader if c["immediate_cold_read"] else writer)
                and c["return_elf"] == c["own_empty_elf"] == program
                and c["returned_marker_identity"] == c["marker"]
                and set(c["actual"]["owned_operations"])
                == {
                    "marker",
                    "dep-graph.bin",
                    "query-cache.bin",
                    "mapped-dep-graph.bin",
                    "mapped-query-cache.bin",
                },
                "cross-reader did not load own clean output",
            )
            read_cross.replay(z, read, label, c, m, base)
            elf = gzip.decompress(read("E/cross-readers/elf/" + program + ".gz"))
            s.need(
                elf.startswith(b"\x7fELF")
                and hashlib.sha256(elf).hexdigest() == program
                and c["first_B"] != program
                and s.required_tests(m["source"]["role"]["commit"])
                <= set(json.loads(read("E/checked-in-tests.json"))["units"]["rustc_incremental"]),
                "different native units or program",
            )
        own = json.loads(read("E/native-shadow/complete.json"))
        checked = json.loads(read("E/checked-in-tests.json"))
        s.need(len(checked["units"]["rustc_incremental"]) == 10
               and checked["units"]["rustc_fs_util"] == [] and len(checked["run_make"]) == 7
               and checked["fixtures"]["ohm-packed-branch-cache"]
               == s.names_for(end["commit"])["changed_files"]["tests/run-make/ohm-packed-branch-cache/rmake.rs"],
               "different real cold-table regression")
        s.need(
            (own["physical_cargo"], own["physical_wild"], own["visits"], own["branches"])
            == (s.reg.ELF, s.reg.WILD_SHA, 16, [17, 29, 47])
            and end["members"] == len(m["files"]) == 81,
            "wrong native scope",
        )
        controls = json.loads(read("E/provider-E/result.json"))
        s.need(
            len(controls) == 6
            and controls["invalid"]["exit"] == 101
            and controls["repair"] == controls["empty-repair"] == controls["returned-A"]
            and [controls[n]["output"] for n in ("cold-A", "first-B", "repair")]
            == ["17 1", "29 2", "29 1"],
            "stale ordinary provider",
        )
    return {
        "manifest": digest,
        "source": end["commit"],
        "delta": end["changed"],
        "driver": end["driver"],
        "members": end["members"],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=int)
    p.add_argument("head")
    p.add_argument("--gh", default="/home/dev-user/.local/bin/gh-auto")
    p.add_argument(
        "--media",
        type=Path,
        help="directory containing the two original ZIPs, named after the official artifacts",
    )
    a = p.parse_args()
    s.load()
    s.need(s.reg.rev(s.HERE.parents[1], "HEAD") == a.head, "check out the exact reviewed source")

    def api(suffix):
        return json.loads(
            subprocess.check_output([a.gh, "api", f"repos/{s.reg.REPO}/actions/runs/{a.run}" + suffix])
        )

    catalog = check(
        a.run, a.head, api(""), api("/attempts/1/jobs")["jobs"], api("/artifacts")["artifacts"]
    )
    if a.media:
        catalog["qualified"] = media(catalog, a.media)
    print(json.dumps(catalog, indent=2))
