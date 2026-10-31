"""Reopen every retained native observation and separate first migration, settled and repair work."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kits import CARGO, ENROLL, HOST, WILD, WILD_HASH, need, sha, write
from observe import calibrated, metadata_stamp
import chunks


def read(p):
    return json.loads(p.read_bytes())


def readgz(p):
    return json.loads(gzip.decompress(p.read_bytes()))


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def archive_bytes(p, size, hash_):
    with subprocess.Popen(["zstd", "-qdc", p], stdout=subprocess.PIPE) as proc:
        h = hashlib.sha256()
        n = 0
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
            n += len(chunk)
            h.update(chunk)
        need(
            proc.wait() == 0 and n == size and h.hexdigest() == hash_,
            "retained complete binary differs: " + str(p),
        )


def one(folder, role, run, head):
    reg = read(folder / "registration.json")
    s = read(folder / "summary.json")
    need(
        s["role"] == reg["role"] == role
        and reg["head"] == head
        and reg["run"] == run
        and reg["sdk_admission"]["head"] == ENROLL["native_qa"],
        "wrong QA role/run/source",
    )
    calibration = read(folder / "calibration/results.json")
    need(len(calibration) == 7, "incomplete PMU calibration")
    for i, (
        _,
        copies,
        counts,
        _,
    ) in calibration.items():
        physical = [read(folder / f"calibration/{i}-{j}.json") for j in range(4)]
        need(
            all(calibrated(v) and v["code"] == 0 for v in physical)
            and [v["instructions"] for v in physical] == counts
            and abs(
                (statistics.median(counts[1::2]) - statistics.median(counts[::2])) / (160000000 * copies) - 1
            )
            < 0.02,
            "physical calibration invalid",
        )
    e2e = role.startswith("e2e-")
    checked = {}
    bad = set()
    edits = {}
    stales = {}
    expected = {"cold", "prior-repeat", "edited", "edit-repeat", "restored", "restore-repeat"} | (
        set() if e2e else {"upgrade-first", "upgrade-second", "invalid", "repaired"}
    )
    phases = (
        {stream + "/" + p for stream in ["pmu", "trace"] for p in expected}
        | {"clean/original", "clean/reversed"}
        | (set() if e2e else {"clean/invalid", "clean/repaired"})
    )
    need(set(s["visits"]) == phases, "omitted/extra physical visit")
    for phase, projection in s["visits"].items():
        d = folder / phase
        stream, label = phase.split("/")
        r = read(d / "visit.json")
        cmd = read(d / "command.json")
        need(
            cmd["argv"] == reg["argv"] and cmd["status"] == r["status"] == projection["status"],
            "changed exposed command",
        )
        raw = [
            json.loads(l)
            for l in gzip.decompress((d / "stdout.jsonl.gz").read_bytes()).splitlines()
            if l.strip()
        ]
        need((raw[-1] if raw else None) == r["terminal"], "bad terminal JSON")
        ledger = gzip.decompress((d / "allocated-files.json.gz").read_bytes())
        table = json.loads(ledger)
        blocks = {tuple(x[1:3]): x[6] for x in table}
        need(
            all(x[0].split("/")[0] in ("target", "shared") for x in table)
            and sum(blocks.values()) * 512 == r["allocated"]["bytes"] == projection["allocated"]
            and sha_b(ledger) == r["allocated"]["ledger_sha256"],
            "different physical disk allocation",
        )
        issuer = r["active_stamp"]
        refs = read(d / "workspace-rmeta.json")
        stale = []
        for k, v in refs.items():
            if v["size"]:
                expected_stamp = metadata_stamp(folder / "rmeta-headers" / (v["sha256"] + ".bin"))
                need(expected_stamp == v["stamp"], "different physical rmeta header")
                if issuer != expected_stamp:
                    stale.append(k)
        need(set(stale) == set(r["stale_metadata"]), "stale workspace output projection differs")
        verdicts = {}
        for retained in sorted(d.glob("installed-reader-*/verdict.json")):
            v = read(retained)
            stderr = gzip.decompress((retained.parent / "stderr.gz").read_bytes())
            errors = [
                j
                for line in stderr.splitlines()
                if line.startswith(b"{") and (j := json.loads(line)).get("level") == "error" and j.get("code")
            ]
            need(v["diagnostics"] == [e["code"]["code"] for e in errors], "different direct rustc diagnostic")
            verdicts[v["sha256"]] = v
        need(
            verdicts == {x["sha256"]: x for x in r["retained_reader"].values()},
            "missing original direct metadata reader",
        )
        for x in r["retained_reader"].values():
            h = x["sha256"]
            archive_bytes(
                folder / "stale-rmeta" / (h + ".rmeta.zst"),
                next(v["size"] for v in refs.values() if v["sha256"] == h),
                h,
            )
        for n, h in r["generated"].items():
            need(
                sha_b(gzip.decompress((folder / "generated" / (h + ".gz")).read_bytes())) == h,
                "wrong generated output: " + n,
            )
        if stream == "pmu":
            cnt = read(d / "whole.json")
            need(
                calibrated(cnt)
                and cnt["code"] == r["status"]
                and cnt["instructions"] == projection["instructions"],
                "unexpected PMU observation",
            )
        if stream == "trace":
            switch = not e2e and label not in ("cold", "prior-repeat")
            name = "trace-new" if switch else "trace-old"
            roster = readgz(folder / f"installs/{name}/installed.json.gz")
            events = readgz(d / "execs.json.gz")
            cpp = roster["bin/rustc"]
            cargo = roster["bin/cargo"]
            w = roster[str(WILD)]
            need(cargo["sha256"] == CARGO and w["sha256"] == WILD_HASH, "unregistered Cargo or Wild")
            actual_r = []
            actual_w = []
            actual_c = []
            for pid, identity, image, argv in events:
                if identity == [cargo["dev"], cargo["ino"]] and argv[1:] == reg["argv"][2:]:
                    actual_c.append(pid)
                if (
                    identity == [cpp["dev"], cpp["ino"]]
                    and "--crate-name" in argv
                    and "--out-dir" in argv
                    and not any(a.startswith("--print") for a in argv)
                ):
                    actual_r.append(pid)
                if identity == [w["dev"], w["ino"]] and "-o" in argv:
                    actual_w.append(pid)
            real = r["physical"]
            need(
                actual_c == real["cargo"]
                and actual_r == [x[0] for x in real["compilers"]]
                and actual_w == [x["pid"] for x in real["wild"]],
                "kernel exec census differs",
            )
        if e2e and r["test"]:
            got = r["test"]
            names = read(d / "actual-test-names.json")
            listing = gzip.decompress((d / "native-list.stdout.gz").read_bytes())
            need(
                sorted(x[:-6] for x in listing.decode(errors="replace").splitlines() if x.endswith(": test"))
                == names
                == got["names"]
                and sha_b(listing) == got["list_sha"],
                "different test set",
            )
            libtest_status = read(d / "native-list.status.json")
            stable = [n for n in names if n.endswith("::inlay_hints_range_past_end_of_cell")]
            need(
                got["list_exit"] == libtest_status
                and got["stable_cases"] == stable
                and got["valid_inventory"]
                == (libtest_status == 0 and len(set(names)) == len(names) > 100 and len(stable) == 1),
                "changed native list verdict",
            )
            for test, expect in got["runtime"].items():
                out = gzip.decompress((d / ("native-" + test.split("::")[-1] + ".stdout.gz")).read_bytes())
                need(
                    expect["code"] == read(d / ("native-" + test.split("::")[-1] + ".status.json"))
                    and expect["one_named"]
                    == (("test " + test + " ... ok").encode() in out and b"1 passed; 0 failed" in out),
                    "changed runtime/snapshot verdict",
                )
            ident = got["elf"]["sha256"]
            elf = read(folder / got["elf"]["native_index"])
            need(
                elf["sha256"] == ident
                and elf["size"] == got["elf"]["size"]
                and any(x[1] == ".text" for x in elf["sections"])
                and elf["segments"],
                "missing complete ELF index",
            )
            divergent = folder / "elf-divergences" / (ident + ".zst")
            if divergent.is_file() and ident not in bad:
                archive_bytes(divergent, elf["size"], ident)
                bad.add(ident)
            edits[phase] = {
                "test_count": len(names),
                "changed_cases": got["new_cases"],
                "test_list_sha256": got["list_sha"],
                "elf": ident,
                "native": got["runtime"],
            }
        if stale:
            stales[phase] = {
                "count": len(stale),
                "active": issuer,
                "old": sorted(set(r["stale_metadata"].values())),
                "confirmed_reader": r["retained_reader"],
            }
        checked[phase] = projection
    if not e2e:
        need(
            chunks.summarize(folder / "semantic-chunks") == s["semantic_content_survey"],
            "content-block readback differs",
        )
        for stream in ("pmu", "trace"):
            before = gzip.decompress(
                (folder / f"installs/{stream}-before/allocated-files.json.gz").read_bytes()
            )
            after = gzip.decompress(
                (folder / f"installs/{stream}-after/allocated-files.json.gz").read_bytes()
            )
            need(before == after, "populated directories changed across the SDK install")
    return {
        "kind": s["kind"],
        "success": s["success"],
        "issues": s["issues"],
        "upgrade_cost": s.get("upgrade_cost"),
        "visits": checked,
        "e2e": edits,
        "stale_user_outputs": stales,
        "semantic_content_survey": s.get("semantic_content_survey"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("panel", choices=["all", "migration", "e2e"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--run", type=int, required=True)
    a = parser.parse_args()
    roles = []
    if a.panel in ("all", "e2e"):
        roles += ["e2e-parent", "e2e-candidate"]
    if a.panel in ("all", "migration"):
        roles += ["stage-to-candidate", "stage-to-sham", "signed-to-candidate"]
    try:
        result = {k: one(a.folder / ("mixed-ruff-" + k), k, a.run, a.head) for k in roles}
        issues = [k + ": " + i for k, z in result.items() for i in z["issues"]]
        if "e2e-parent" in result:
            for phase, p in result["e2e-parent"]["e2e"].items():
                c = result["e2e-candidate"]["e2e"].get(phase)
                if not c or (p["native"], p["test_list_sha256"]) != (c["native"], c["test_list_sha256"]):
                    issues.append("compiler arms disagree on actual test program " + phase)
        write(
            a.output,
            {
                "run": a.run,
                "head": a.head,
                "native_run": ENROLL["native_run"],
                "panel": a.panel,
                "roles": result,
                "issues": issues,
                "success": not issues,
            },
        )
    except Exception as exc:
        write(
            a.output,
            {"run": a.run, "head": a.head, "panel": a.panel, "readback_error": str(exc), "success": False},
        )
        raise
    sys.exit(1 if issues else 0)
