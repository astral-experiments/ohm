"""Reopen the complete ordinary Cargo hardware and product receipts, with no runner filesystem."""

import argparse
import gzip
import json
from pathlib import Path
import re
import stat
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol as p
import inventory
import intake
import parser_tests
import instrument
import reopen as base

f, c = p.f, p.c


def counter_files(z, temp):
    prefixes = ("calibration/", "counter-programs/", *[r + "/inventory/edited/trace/" for r in p.ROLES])
    total = 0
    count = 0
    for label in z.namelist():
        if not label.startswith(prefixes) or label.endswith("/"):
            continue
        path = Path(label)
        f.require(
            not path.is_absolute() and ".." not in path.parts and str(path) == label, "unsafe raw member"
        )
        with z.open(label) as src:
            body = src.read((4 << 20) + 1)
        count += 1
        total += len(body)
        f.require(
            0 < len(body) <= 4 << 20 and count < 2800 and total < 48 << 20,
            "oversized raw calibration/trace",
        )
        out = temp / path
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("xb") as dst:
            dst.write(body)


def source(obs, state):
    refs = {"HEAD": f"ref: {f.BRANCH}\n", f.BRANCH: f.B + "\n"}
    f.require(
        set(obs["watched"]) == set(refs)
        and all(
            len(obs["watched"][k]) == 5
            and obs["watched"][k][0] == f.sha(txt.encode())
            and min(obs["watched"][k][1:]) > 0
            for k, txt in refs.items()
        ),
        "changed watched Git ref",
    )
    f.require(
        obs["head"] == f.B
        and obs["tree"] == f.B_TREE
        and obs["branch"] == f.BRANCH
        and re.fullmatch("[0-9a-f]{64}", obs["index_sha256"])
        and obs["source_sha256"] == f.SOURCE_SHA[state]
        and obs["status"] == ("" if state == "baseline" else " M " + f.SRC),
        "wrong live commit/index/production path",
    )


def rows(z, prefix):
    return list(map(json.loads, gzip.decompress(z.read(prefix + "/cargo.stdout.gz")).splitlines()))


def review(z, temp, head, collect, contract, previous=None):
    get = lambda n: base.record(z, n)
    book = get("catalog.json")
    en = get("enrollment.json")
    f.require(
        en == intake.enroll(book, head, en["runner"], en["boot"])
        and (previous is None or book["previous"] == previous),
        "different enrolled original(s)",
    )
    before = get("resources-before-sdk.json")
    f.require(
        min(before["work"], before["receipts"]) >= 25 << 30 and before["effective"] >= 16 << 30,
        "resources before SDK admission",
    )
    root, work, selectors, sdk, _ = base.read_product(z)
    repo = root / "ruff"
    collection = get("collection.json")
    f.require(
        "refusal.txt" not in z.namelist()
        and collection["roles"] == list(p.ROLES)
        and collection["lanes"] == {k: list(v) for k, v in p.LANES.items()},
        "incomplete histories",
    )
    rehearsal = get("checkout-preflight.json")
    f.require(
        rehearsal["refused"]
        == ["unexpected working file", "staged parser edit", "incorrect parser body"]
        and len(rehearsal["states"]) == 5,
        "missing real Git rehearsal",
    )
    for word, st in zip(
        ["baseline", "edited", "invalid", "edited", "baseline"], rehearsal["states"], strict=True
    ):
        source(st, word)
    f.require(
        rehearsal["states"][0] == rehearsal["states"][4]
        and rehearsal["states"][1] == rehearsal["states"][3]
        and len({s["index_sha256"] for s in rehearsal["states"]}) == 1,
        "Git apply/reverse/repair changed that checkout",
    )
    source(collection["source"], "baseline")
    index = collection["source"]["index_sha256"]
    raw, pmu = instrument.compile_sources(collect, contract, temp / "counter-source")
    topo = inventory.decoder(raw)
    counter_files(z, temp)
    cal = pmu.calibration(temp / "counter-programs", temp, replay=True)
    z_names = set(z.namelist())
    expected_clocks = set()
    results = {}
    expected_bodies = set()
    names = set(get("registered-cases.json"))
    for role in p.ROLES:
        ctrl = {}
        dirty_visits = []
        clocks = []
        counts = None
        reference_error = None
        cmd = p.command(role)
        plan_prefix = role + "/plan"
        plan_cmd = [*cmd[:3], "-Zunstable-options", "--unit-graph", *cmd[3:]]
        f.require(
            get(plan_prefix + "/invocation.json") == dict(argv=plan_cmd, exit=0, cwd=str(repo)),
            "different unit plan",
        )
        (plan_body,) = rows(z, plan_prefix)
        plan = p.unitplan(plan_body, role, repo)
        for lane, phases in p.LANES.items():
            for idx, phase in enumerate(phases):
                name = "/".join((role, lane, phase))
                mark = p.STATE.get(phase, phase)
                err = mark == "invalid"
                before = get(name + "/source-before.json")
                source(before, mark)
                f.require(
                    before == get(name + "/source-after.json")
                    and before["index_sha256"] == index
                    and before["watched"] == collection["source"]["watched"],
                    "changed/dirty Git index or source",
                )
                if idx == 0:
                    roots = get(name + "/empty-roots.json")
                    f.require(
                        set(roots) == {str(work / "target"), str(work / "build")}
                        and len({tuple(x[:2]) for x in roots.values()}) == 2
                        and all(len(x) == 3 and x[2] == [] and min(x[:2]) > 0 for x in roots.values()),
                        "not independently empty",
                    )
                want = 101 if err else 0
                prefix = []
                if phase == "edited" and lane.startswith("plain-"):
                    clock = name + "/clock.json"
                    expected_clocks.add(clock)
                    prefix = [str(root / "counter-kit/bin/plain"), str(root / "logs" / clock)]
                    clocks.append(instrument.clock_value(get(clock)))
                if phase == "edited" and lane == "inventory":
                    prefix = [
                        str(root / "counter-kit/bin/tree"),
                        str(root / "logs" / name / "trace"),
                        "topology",
                        *[v[2] for v in (selectors[n] for n in topo.ROLES)],
                    ]
                f.require(
                    get(name + "/invocation.json")
                    == dict(argv=[*prefix, *cmd], cwd=str(repo), exit=want),
                    "different application, root, wrapper or exit",
                )
                raw_rows = rows(z, name)
                if err:
                    diag = p.error(raw_rows)
                    f.require(diag == get(name + "/diagnostic.json"), "recorded typed error differs")
                    if lane == "empty-invalid":
                        reference_error = diag
                    else:
                        f.require(diag == reference_error, "real error drift after previous success")
                    continue
                graph, dirty, products, binary = p.graph(raw_rows, role, repo, work)
                p.validate_planned(plan, products)
                f.require(
                    get(name + "/roster.json.gz") == {"graph": graph, "dirty": dirty}
                    and (idx != 0 or graph == dirty),
                    "wrong Cargo roster/freshness",
                )
                desc = get(name + "/elf.json.gz")
                if role == "cli":
                    cli = base.replay_native.native_verdict(z, name, "B")
                    base.actual_externs(z, name, products, root)
                    f.require(
                        desc == {k: cli[k] for k in ("cli", "reader")}, "physical CLI or typed reader"
                    )
                    syntax = get(name + "/syntax.json.gz")
                    f.validate(syntax, binary, mark)
                    f.require(
                        (syntax["sha256"], syntax["bytes"])
                        == (desc["cli"]["whole"], desc["cli"]["size"]),
                        "different executable supplied the syntax verdict",
                    )
                else:
                    f.require(set(desc) == {"fixtures"}, "wrong native parser outputs")
                    execution = get(name + "/test-executable.json")
                    physical = execution["before"]
                    f.require(
                        physical == execution["after"]
                        and physical["path"] == str(binary)
                        and (physical["sha256"], physical["size"])
                        == (desc["fixtures"]["whole"], desc["fixtures"]["size"])
                        and physical["inode"] > 0
                        and physical["mode"] & 0o111,
                        "different native parser executable at test time",
                    )
                    parser_tests.verify_calls(
                        get(name + "/test-suite.json.gz"), names, mark, binary, repo
                    )
                if lane.startswith("empty-"):
                    ctrl[mark] = (graph, desc)
                    for k, v in desc.items():
                        asset = "native-bodies/" + v["whole"] + ".zst"
                        expected_bodies.add(asset)
                        base.replay_elf.verify(
                            z, asset, v, {"cli": "ruff", "reader": "ohm_branch_reader"}.get(k)
                        )
                else:
                    f.require(
                        (graph, desc) == ctrl[mark],
                        "whole executable, executable sections or raw roster differs from its own empty build",
                    )
                if phase == "edited" and lane in ("plain-1", "inventory", "plain-2"):
                    dirty_visits.append(dirty)
                if phase == "edited" and lane == "inventory":
                    counts = inventory.read(
                        temp / name / "trace",
                        topo,
                        role,
                        repo,
                        work,
                        products,
                        get(name + "/output-inodes.json.gz"),
                        sdk,
                        selectors,
                    )
                    f.require(counts == get(name + "/inventory.json"), "physical kernel census differs")
        key = "cli" if role == "cli" else "fixtures"
        f.require(
            len(clocks) == 2
            and len(dirty_visits) == 3
            and dirty_visits[0] == dirty_visits[1] == dirty_visits[2]
            and counts
            and ctrl["baseline"][1][key]["whole"] != ctrl["edited"][1][key]["whole"],
            "missing changed product or mismatched applications",
        )
        results[role] = dict(
            plain_instructions=clocks,
            dirty=len(dirty_visits[0]),
            native=counts,
            references={k: {a: v["whole"] for a, v in ref[1].items()} for k, ref in ctrl.items()},
            spread_within_two_percent=50 * (max(clocks) - min(clocks)) <= min(clocks),
        )
    f.require(
        {n for n in z_names if n.endswith("/clock.json")} == expected_clocks
        and {n for n in z_names if n.startswith("native-bodies/") and n.endswith(".zst")}
        == expected_bodies,
        "extra measured window or native body",
    )
    return dict(
        enrollment=en,
        observations=results,
        calibrated=sum(len(v[0]) for v in cal["whole28"].values()),
        causal_speedup_measured=False,
    )


def official(meta, archive, head):
    run, job, asset = (meta[n] for n in ("run", "job", "artifact"))
    f.require(
        run["repository"]["full_name"] == c.REPO
        and run["head_sha"] == head
        and run["head_branch"] == p.BRANCH
        and run["run_attempt"] == 1
        and run["path"] == ".github/workflows/ci.yml"
        and run["event"] == "workflow_dispatch"
        and run["status"] == "completed"
        and run["conclusion"] == "success",
        "wrong official terminal",
    )
    needed = {
        "Install signed GNU SDK and bind previous boots",
        "Run the two normal fixed-branch workloads",
        "Independently reopen the ordinary counters and native products",
    }
    f.require(
        job["run_id"] == run["id"]
        and job["name"] == p.JOB
        and job["conclusion"] == "success"
        and needed <= {i["name"] for i in job["steps"] if i["conclusion"] == "success"},
        "missing genuine terminal steps",
    )
    f.require(
        asset["workflow_run"]["id"] == run["id"]
        and asset["name"] == "signed-gnu-ruff-one-file-parser"
        and asset["size_in_bytes"] == archive.stat().st_size
        and asset["digest"] == "sha256:" + c.sha(archive),
        "wrong official artifact",
    )
    return run["id"], job["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--directory", type=Path)
    sources.add_argument("--zip", type=Path)
    for n in ("collector", "contract"):
        parser.add_argument("--" + n, type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as storage:
        temp = Path(storage)
        if args.directory:
            result = review(
                base.Directory(args.directory), temp, args.head, args.collector, args.contract
            )
        else:
            f.require(
                args.catalog and args.previous,
                "official run/job/artifact and independently enrolled prior boots required",
            )
            ids = official(c.read(args.catalog), args.zip, args.head)
            with zipfile.ZipFile(args.zip) as z:
                names = z.namelist()
                f.require(
                    len(set(names)) == len(names) < 12000
                    and sum(m.file_size for m in z.infolist()) < 768 << 20
                    and all(
                        not Path(m.filename).is_absolute()
                        and ".." not in Path(m.filename).parts
                        and not stat.S_ISLNK(m.external_attr >> 16)
                        for m in z.infolist()
                    ),
                    "unbounded or unsafe input",
                )
                result = review(z, temp, args.head, args.collector, args.contract, c.read(args.previous))
                f.require(
                    result == base.record(z, "accepted.json")
                    and ids == (result["enrollment"]["run"], result["enrollment"]["job"]),
                    "different original readback",
                )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
