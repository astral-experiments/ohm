"""Bind the two external native gates by immutable Actions originals before opening a hardware event."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-gnu-renderer-pfc-hardware-20261031"
OBSERVERS = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
PLAN = "70076984ab6feb82a8a9eae43cb9a9c34eec7a9cc42a50305c018391c14afe66"
AMENDMENT = "1697b1e098ef8398714d55023da7a46c2838d19447108176eb8606bd66296a01"
CONDITIONAL_ORDER = "2bd86204b49982bcd48d0861d481a0dfbc53df9324a210a8583f16b81d408168"
RUST = {
    "P": "4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e",
    "F": "51e72261c0b36dfd49c078b35732956d6b950e8e",
    "C": "11876886792274b44a9a37567fbac57bf843a24c",
}
CARGO = "9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
STUDIES = ("source-map", "notebook")
POSITIONS = {
    "01": {"roles": ["P", "F", "C"], "histories": list(STUDIES)},
    "02": {"roles": ["C", "F", "P"], "histories": list(reversed(STUDIES))},
}
NATIVE_ARCHIVES = {"gnu-renderer-qualified-native", "gnu-renderer-source-native-observations"}


def need(value, msg):
    if not value:
        raise ValueError(msg)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def put(p, r):
    with Path(p).open("x") as f:
        json.dump(r, f, sort_keys=True, indent=2)
        f.write("\n")


def required_digest(s):
    return isinstance(s, str) and bool(re.fullmatch("[0-9a-f]{64}", s))


def registration(phase="inspect"):
    r = json.loads((HERE / "registration.json").read_bytes())
    need(phase in ("inspect", "qualify", "screen"), "unknown enrollment phase")
    need(
        sha(HERE / "PLAN.md") == r["plan_sha256"] == PLAN
        and sha(HERE / "PLAN-V2.md") == r["amendment_sha256"] == AMENDMENT
        and {k: v["commit"] for k, v in r["role_trees"].items()} == RUST
        and sha(HERE / "cohort-order.json") == r["conditional_cohort_order_sha256"] == CONDITIONAL_ORDER
        and r["positions"] == POSITIONS
        and r["observers"] == OBSERVERS,
        "registration changed",
    )
    if phase == "inspect":
        return r
    s = r["source"]
    need(isinstance(s, dict), "no qualifying three-role native source run")
    need(
        s["repo"] == REPO
        and s["run"] not in [x["run"] for x in r["excluded_source_runs"]]
        and s["attempt"] == 1
        and re.fullmatch("[0-9a-f]{40}", s["head"])
        and s["branch"] == "charlie/qa-gnu-renderer-cgu-source-20261031"
        and s["jobs"] == ["native"]
        and len(s["job_ids"]) == 1,
        "incorrect source job enrollment",
    )
    need(
        isinstance(s["artifacts"], dict)
        and set(s["artifacts"]) == NATIVE_ARCHIVES
        and required_digest(s["manifest_sha256"]),
        "native originals not enrolled",
    )
    for name in (
        "adapter",
        "oracle",
        "mono",
        "membership",
        *(("whole_oracle",) if phase == "screen" else ()),
    ):
        packet = r[name]
        need(
            isinstance(packet, dict)
            and required_digest(packet["sha256"])
            and packet["file"] == name + ".tar.gz"
            and sha(HERE / "packets" / packet["file"]) == packet["sha256"]
            and isinstance(packet["files"], dict)
            and all(legal(n) and required_digest(h) for n, h in packet["files"].items()),
            "unbound or modified " + name + " packet",
        )
    if phase == "screen":
        g = r["structural"]
        need(
            isinstance(g, dict)
            and g["run"] not in [x["run"] for x in r["excluded_qualification_runs"]]
            and g["branch"] == BRANCH
            and g["jobs"] == ["qualify (gate)"]
            and set(g["artifacts"]) == {"gnu-renderer-pfc-qualify-gate"}
            and required_digest(g["certificate_sha256"]),
            "no complete official ordinary qualification",
        )
        need(
            r["root_acceptance"]
            == {
                "source": s["head"],
                "source_manifest": s["manifest_sha256"],
                "plan": PLAN,
                "amendment": AMENDMENT,
                "structural_certificate": g["certificate_sha256"],
                "whole_oracle": r["whole_oracle"]["sha256"],
            },
            "root has not admitted this structural evidence",
        )
    return r


def official(endpoint, dest=None):
    cmd = [os.environ.get("PFC_GH", "gh"), "api", "repos/" + REPO + "/actions/" + endpoint]
    if dest is None:
        return json.loads(subprocess.check_output(cmd))
    with dest.open("xb") as f:
        subprocess.run(cmd, stdout=f, check=True)


def run_header(s):
    need(
        s["repo"] == REPO
        and s["attempt"] == 1
        and len(s["jobs"]) == len(s["job_ids"])
        and len(set(s["job_ids"])) == len(s["job_ids"]),
        "foreign run enrollment",
    )
    base = "runs/" + str(s["run"])
    meta = official(base)
    need(
        (
            meta["id"],
            meta["run_attempt"],
            meta["head_sha"],
            meta["head_branch"],
            meta["repository"]["full_name"],
            meta["event"],
            meta["status"],
            meta["conclusion"],
        )
        == (
            s["run"],
            s["attempt"],
            s["head"],
            s["branch"],
            REPO,
            "workflow_dispatch",
            "completed",
            "success",
        ),
        "run not a successful exact registered attempt",
    )
    jobs = official(base + "/attempts/1/jobs?per_page=100")
    need(jobs["total_count"] == len(jobs["jobs"]) == len(s["jobs"]), "job list differs or exceeds one page")
    actual = sorted((j["name"], j["id"], j["head_sha"], j["status"], j["conclusion"]) for j in jobs["jobs"])
    expect = sorted((n, i, s["head"], "completed", "success") for n, i in zip(s["jobs"], s["job_ids"]))
    need(actual == expect, "native job IDs or verdicts differ")
    return {"run": meta, "jobs": jobs}


def archive(s, name, entry, destination):
    idx = entry["id"]
    raw = official("artifacts/" + str(idx))
    h = entry["sha256"]
    length = entry["bytes"]
    need(
        type(idx) == int and type(length) == int and 0 < length < 4 * 2**30 and required_digest(h),
        "invalid official ZIP enrollment",
    )
    need(
        (
            raw["id"],
            raw["name"],
            raw["size_in_bytes"],
            raw["digest"],
            raw["expired"],
            raw["workflow_run"]["id"],
            raw["workflow_run"]["head_sha"],
        )
        == (idx, name, length, "sha256:" + h, False, s["run"], s["head"]),
        "artifact metadata is not the registered original: " + name,
    )
    official("artifacts/" + str(idx) + "/zip", destination)
    need(destination.stat().st_size == length and sha(destination) == h, "artifact digest differs: " + name)
    with zipfile.ZipFile(destination) as z:
        ns = z.namelist()
        need(len(ns) == len(set(ns)) and all(legal(n) for n in ns), "ambiguous ZIP member")
    return raw


def legal(name):
    path = PurePosixPath(name)
    return bool(name and not path.is_absolute() and ".." not in path.parts and "\\" not in name)


def one(z, suffix):
    candidates = [n for n in z.namelist() if n == suffix or n.endswith("/" + suffix)]
    need(len(candidates) == 1, ("ambiguous/missing ZIP suffix", suffix, candidates))
    return candidates[0]


def members(r, source_code, kit_zip, logs_zip, transfer):
    sys.path.insert(0, str(source_code))
    import build

    s = r["source"]
    transfer.mkdir()
    with zipfile.ZipFile(kit_zip) as z:
        names = {"P-sdk.tar.zst", "driver-F.zst", "driver-C.zst", "manifest.json"}
        vs = [n for n in z.namelist() if not n.endswith("/")]
        need(set(Path(n).name for n in vs) == names and len(vs) == len(names), "source transfer shape")
        for filename in vs:
            path = transfer / Path(filename).name
            with z.open(filename) as f, path.open("xb") as out:
                import shutil

                shutil.copyfileobj(f, out, 1024 * 1024)
    mp = transfer / "manifest.json"
    need(sha(mp) == s["manifest_sha256"], "different source SDK manifest")
    m = json.loads(mp.read_bytes())
    need(
        (
            m["qa"],
            int(m["run"]),
            int(m["attempt"]),
            m["operative_cargo"],
            m["native_linker"],
            m["review_base"],
        )
        == (s["head"], s["run"], s["attempt"], CARGO, WILD, RUST["P"]),
        "wrong SDK compiler/Cargo/Wild source",
    )
    need(
        {k: v["source"]["commit"] for k, v in m["roles"].items()} == RUST
        and len(m["files"]) == m["common_member_count"] + 1,
        "role or SDK membership differs",
    )
    for role, expected in r["role_trees"].items():
        observed = m["roles"][role]["source"]
        need(
            all(observed.get(k) == v for k, v in expected.items()),
            "different library/bootstrap/compiler/test tree in " + role,
        )
    need(
        set(m["products"]) == names - {"manifest.json"}
        and all([sha(transfer / n), (transfer / n).stat().st_size] == rr for n, rr in m["products"].items()),
        "original complete transfer changed",
    )
    actual = {}
    with zipfile.ZipFile(logs_zip) as z:
        merged = json.loads(z.read(one(z, "receipts/complete.json")))
        need(merged == m, "source post-restoration verdict is not the official manifest")
        for role in RUST:
            prefix = "receipts/" + role + "/"
            raw = z.read(one(z, prefix + "physical-files.json"))
            phys = json.loads(raw)
            expected = m["files"].copy()
            expected[m["driver"]] = m["roles"][role]["driver"]
            need(
                phys == expected and digest(raw) == m["roles"][role]["manifest_sha256"],
                "independent full-source SDK members differ " + role,
            )
            successes = {}
            for case in (*build.BASE_CONTROLS, build.FORWARD_TEST, build.CALLABLE_TEST):
                command = json.loads(z.read(one(z, prefix + case + ".command.json")))
                data = z.read(one(z, prefix + case + ".log"))
                want = (
                    case in build.BASE_CONTROLS or role == "C" or (role == "F" and case == build.FORWARD_TEST)
                )
                need(
                    digest(data) == command["output_sha256"]
                    and command["argv"][0] == "./x"
                    and command["argv"][-1] == "tests/run-make/" + case,
                    "foreign native fixture",
                )
                build.verdict(data.decode(errors="replace"), case, want, command["returncode"])
                successes[case] = [want, command["returncode"], digest(data)]
            for tag in ("build", "test"):
                linked = json.loads(z.read(one(z, prefix + tag + "-linkers.json")))
                need(
                    linked and all(i["sha256"] == WILD for i in linked),
                    "source native linker control differs",
                )
            actual[role] = successes
    return {
        "manifest_sha256": sha(mp),
        "driver": m["driver"],
        "file_count": len(m["files"]),
        "all_source_fixtures": actual,
    }


def provenance(r, phase, root, source_code):
    inbox = root / "inbox"
    inbox.mkdir()
    gates = ["source"] if phase == "qualify" else ["source", "structural"]
    result = {"artifacts": {}}
    for tag in gates:
        v = r[tag]
        result[tag] = run_header(v)
        for name, entry in v["artifacts"].items():
            need(
                re.fullmatch("[A-Za-z0-9_.-]+", name) and name not in result["artifacts"],
                "ambiguous registered ZIP name",
            )
            result["artifacts"][name] = archive(v, name, entry, inbox / (name + ".zip"))
    result["matched_source"] = members(
        r,
        source_code,
        inbox / "gnu-renderer-qualified-native.zip",
        inbox / "gnu-renderer-source-native-observations.zip",
        root / "transfer",
    )
    if phase == "screen":
        from evidence import qualify_zip

        result["matched_structural"] = qualify_zip(
            inbox / "gnu-renderer-pfc-qualify-gate.zip", r, root / "qualified-cells"
        )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["inspect", "qualify", "screen"])
    a = p.parse_args()
    r = registration(a.phase)
    print(json.dumps(r, indent=2) if a.phase == "inspect" else r["source"]["head"])
