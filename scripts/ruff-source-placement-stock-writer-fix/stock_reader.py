"""Read the original native, ELF, full-kernel, allocation, hardware and peak records from one triplet."""

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_artifacts as artifacts
import stock_footer as footer
import stock_scope as scope
import stock_gate
import readback as old
from stock_scope import INTERNAL

need, read, whole = scope.base.need, old.read, old.whole
D = "physical/"


def installed(z, entry, end, study):
    role = old.raw.checked_json(z, D + "physical-roles.json", end["physical"])
    need(
        role["aliases"] == INTERNAL
        and set(role["kits"]) == set(INTERNAL.values())
        and type(role["parent_member_count"]) is int,
        "different role population",
    )
    pair = {}
    reg = {}
    for label, prefix, field, factory, qa in (
        (
            "C3b",
            "guarded-",
            "guarded_source_qualification",
            scope.GUARDED_FACTORY,
            scope.GUARDED_QA,
        ),
        ("Stock4", "", "source_qualification", scope.STOCK_FACTORY, scope.STOCK_QA),
    ):
        proof = old.raw.checked_json(z, D + prefix + "source-qualification.json", role[field])
        with scope.product(label) as rec:
            reg[label] = rec
        need(
            proof["source"] == reg[label]["roles"]
            and proof["seal"]["sha256"] == entry["products"][label]
            and proof["factory_run"] == entry["factory"][label] == factory
            and proof["factory_qa"] == qa
            and proof["seal"]["boot"] != entry["boot"],
            "different native factory, source or boot",
        )
        pair[label] = proof
    preliminary = old.raw.checked_json(
        z, D + "initial-two-physical-roles.json", role["initial_two_roles"]
    )
    need(
        set(preliminary["kits"]) == {"P", "C"}
        and all(
            preliminary["kits"][r] == role["kits"][r]
            and preliminary["documentation"][r] == role["documentation"][r]
            for r in ("P", "C")
        ),
        "initial independent Stock4 runtime changed",
    )
    oldp = read(z, D + "guarded-P-source-kit.json")
    newp = read(z, D + "P-source-kit.json")
    need(
        oldp == newp
        and newp["commit"] == scope.P
        and pair["C3b"]["physical"]["P"] == pair["Stock4"]["physical"]["P"],
        "independently built physical parent manifests differ",
    )
    members = reg["Stock4"]["signed_cargo"]["members"]
    need(
        not (set(members) & set(newp["files"]))
        and role["parent_member_count"] == len(newp["files"]) + len(members),
        "not the exact authenticated complete number of compiler and signed runtime members",
    )
    docs = {
        family: read(z, D + pre + "docs-qualification.json")
        for family, pre in (("Stock4", ""), ("C3b", "guarded-"))
    }
    need(
        docs["C3b"]["actual"]["P"]["rustdoc"] == docs["Stock4"]["actual"]["P"]["rustdoc"],
        "parent documentation changed",
    )
    for label, internal in INTERNAL.items():
        family = "C3b" if label == "C3b" else "Stock4"
        orig = "P" if label == "P" else "C"
        prefix = "guarded-" if label == "C3b" else ""
        src = read(z, D + prefix + orig + "-source-kit.json")
        refs = role["kits"][internal]
        old.kit_sources(
            refs, src, pair[family]["physical"][orig], reg[family]["signed_cargo"]["members"]
        )
        doc = role["documentation"][internal]
        need(
            src["commit"] == study["source"][label]
            and doc["rustdoc"] == docs[family]["actual"][orig]["rustdoc"][0]
            and doc["html"] == whole(z, D + "doc-control-" + internal + "/actual.html")
            and all(doc["actual_libs"][k]["sha"] == refs[k]["sha"] for k in ("driver", "llvm")),
            "different actual source or documentation",
        )
    need(
        len({v["driver"]["sha"] for v in role["kits"].values()}) == 3
        and all(
            len({v[n]["sha"] for v in role["kits"].values()}) == 1
            for n in ("cargo", "wild", "llvm")
        )
        and all(role["versions"][r] == role["versions"]["P"] for r in INTERNAL.values()),
        "distinct executing compilers and matched tool identities required",
    )
    return role, {r: p["seal"]["boot"] for r, p in pair.items()}


def native_gate(z, entry, study):
    data = old.raw.checked_json(z, D + "previous-gate.json", entry["accepted"])
    frozen = scope.read(scope.HERE / "native-enrollment.json")
    stock_gate.sealed(data, study)
    need(
        (data["run"], data["qa"]) == (frozen["run"], frozen["qa"])
        and data["migration"]["verified"]
        and data["protocol"] == frozen["protocol"],
        "wrong true native prerequisites",
    )
    return data


def scan(z, run, head, slot):
    study = scope.bind()
    assignments = scope.schedule(study)
    row = study["blocks"][slot - 1]
    items = z.infolist()
    need(
        len(items) == len(set(x.filename for x in items))
        and sum(x.file_size for x in items) < 112 << 30
        and all(x.file_size < 8 << 30 for x in items)
        and z.testzip() is None,
        "unbounded, repeated or corrupt native artifact",
    )
    traces = defaultdict(list)
    for x in items:
        if re.search(r"/trace/exec\.\d+$", x.filename):
            traces[x.filename.split("/trace/exec.")[0]].append(x.filename)
    end = read(z, D + "complete.json")
    e = old.raw.checked_json(z, D + "entry.json", end["entry"])
    need(
        (e["qa"], e["run"], e["slot"]) == (head, run, slot)
        and e["assignment"] == row
        and e["suites"] == row["suites"]
        and e["sources"] == end["sources"] == study["source"]
        and e["internal_order"] == [INTERNAL[n] for n in assignments[slot - 1]]
        and e["protocol"] == scope.base.sha(scope.HERE / "selected-study.json")
        and end["previous_gate"] == e["accepted"]
        and end["kinds"] == INTERNAL,
        "different three-way assignment, source or study",
    )
    roles, factory_boots = installed(z, e, end, study)
    prior = native_gate(z, e, study)
    oldboots = {
        x["boot"]
        for x in json.loads((scope.HERE / "native-enrollment.json").read_bytes())[
            "previous_excluded"
        ]
    }
    oldboots.update(factory_boots.values())
    oldboots.update(v["boot"] for v in prior["admissions"].values())
    oldboots.add(prior["migration"]["boot"])
    need(e["boot"] not in oldboots, "previously used physical boot")
    calibration = old.raw.calibration(z)
    bodies = old.raw.verify_bytes(z)
    caches = {r: {} for r in INTERNAL}
    counts = {}
    phases = {}
    verdicts = {}
    rosters = {}
    names = {}
    for suite in row["suites"]:
        prefix = D + suite + "/"
        st = end["reports"][suite]
        vals = old.raw.checked_json(z, prefix + "acquired.json", st["acquired"])
        registry = old.raw.checked_json(z, prefix + "registry.json", st["registry"])
        need(
            st["command"] == study["suites"][suite]["cargo"]
            and set(vals) == set(INTERNAL.values())
            and registry["autocfg-1.5.0.crate"]
            == json.loads((old.WORKFLOW / "worker.json").read_bytes())["autocfg"],
            "changed original workspace, command or driver set",
        )
        wanted = old.PHASES + (("negative", "restored-new") if suite == "e2e" else ())
        counts[suite] = {}
        phases[suite] = {}
        verdicts[suite] = {}
        rosters[suite] = {}
        names[suite] = {}
        for ext in row["roles"]:
            r = INTERNAL[ext]
            role = roles["kits"][r]
            need(set(vals[r]) == set(wanted), "incomplete original phase history")
            pcm, ctrl, vv, rg = {}, {}, {}, {}
            for ph in wanted:
                folder = (
                    prefix
                    + r
                    + (
                        "-edit/"
                        if ph in ("old", "new", "unchanged", "invalid", "repair")
                        else "-clean/"
                    )
                    + ph
                )
                record = vals[r][ph]
                native = old.raw.phase_read(
                    z,
                    folder,
                    ph,
                    suite,
                    "score",
                    r,
                    record,
                    role,
                    roles["sdk"],
                    bodies,
                    traces[folder],
                )
                version = 4 if r == "C" else 3
                with patch.object(
                    old.storage, "parse_footer", lambda raw: footer.parse(raw, version)
                ):
                    disk = old.storage_read(z, folder, caches[ext])
                mem = old.rss_read(z, folder, "score", suite, ph, role["front"]["id"][:2])
                need(
                    r != "P" or disk["optional_tail_bytes"] == 0,
                    "candidate optional records present on parent",
                )
                ctrl[ph] = {"storage": disk, "rss": mem}
                rg[ph] = {
                    "true_rustcs": native["compilers"],
                    "actual_native": native["wild"],
                    "autocfg_probes": native["probes"],
                }
                vv[ph] = {
                    key: record[key]
                    for key in ("elf", "verdict", "error", "raw_roster")
                    if key in record
                }
                if native["pm"] is not None:
                    pcm[ph] = native["pm"]
            for ph in (
                "new",
                "unchanged",
                "repair",
                *(("restored-new",) if suite == "e2e" else ()),
            ):
                need(
                    all(
                        vals[r][ph][key] == vals[r]["clean-new"][key]
                        for key in ("elf", "verdict", "inventory")
                    ),
                    "complete independent true empty oracle differs",
                )
            need(
                set(pcm) == {"old", "new", "unchanged"}
                and vals[r]["old"]["elf"] != vals[r]["new"]["elf"]
                and vals[r]["invalid"]["error"] == "E0308",
                "missing genuine edit, error or hardware cells",
            )
            if suite == "e2e":
                need(
                    vals[r]["old"]["verdict"]["count"] == 151
                    and vals[r]["new"]["verdict"]["count"] == 152
                    and vals[r]["negative"]["verdict"]["negative_left"] != old.raw.e2e.WARNING,
                    "different actual contrary e2e or test population",
                )
            counts[suite][ext] = pcm
            phases[suite][ext] = ctrl
            verdicts[suite][ext] = vv
            rosters[suite][ext] = rg
            ids = {a for v in vals[r].values() for a in v["compiler_namespace"]["ids"]}
            need(len(ids) == 1, "one physical participant changed ordinary Cargo namespace")
            names[suite][ext] = next(iter(ids))
        need(
            len(set(names[suite].values())) == 3, "aliased physical source-aware Cargo directories"
        )
        for ph in wanted:
            p = vals["P"][ph]
            dirs = p["compiler_namespace"]["paths"]
            expect = old.shards.comparable(p, dirs)
            for r in INTERNAL.values():
                v = vals[r][ph]
                need(
                    dirs == v["compiler_namespace"]["paths"]
                    and old.shards.comparable(v, dirs) == expect,
                    "literal root argv or native verdicts differ beyond the physical SDK shards",
                )
    return {
        "slot": slot,
        "study": e["protocol"],
        "entry_sha256": end["entry"],
        "terminal_sha256": whole(z, D + "complete.json"),
        "run": run,
        "qa": head,
        "assignment": row,
        "source": study["source"],
        "boot": e["boot"],
        "forbidden_boots": sorted(oldboots),
        "prior_native": prior,
        "kits": {ext: roles["kits"][r] for ext, r in INTERNAL.items()},
        "factory": e["factory"],
        "kit_products": e["products"],
        "roles_sha256": end["physical"],
        "calibration": calibration,
        "namespaces": names,
        "counts": counts,
        "native_rosters": rosters,
        "oracles": verdicts,
        "controls": phases,
        "raw_consumer_bodies": {k: sorted(v) for k, v in bodies.items()},
    }


def main(slot, dest):
    scope.bind()
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as d:
        p = Path(d) / "physical.zip"
        receipt = artifacts.receive(run, head, "three", slot, "raw", p, 7 << 30)
        with zipfile.ZipFile(p) as z:
            data = scan(z, run, head, slot)
    data["raw"] = receipt
    scope.base.save(dest, data)
    print("All physical measurements and every clean oracle reopened on new slot", slot, flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), Path(sys.argv[2]))
