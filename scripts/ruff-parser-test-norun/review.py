"""Independently reconstruct each block from a server-hashed original Actions ZIP."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess as sp
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from records import digest, dump, file_hash, load, native_checks, overflow, roster, test_executable

PLAN = load(HERE / "registration.json")
BASE = load(HERE.parent / "ruff-static-array-cost" / "registration.json")


def instructions(r):
    assert r["status"] == 0 and r["pid"] > 0 and r["enabled"] == r["running"] > 0
    assert r["instructions"] > 0
    return r["instructions"]


def read_exec(z, prefix, installed):
    images, selected = {}, []
    whole = []
    for line in z.read(prefix + "/tasks/epochs.tsv").decode().splitlines():
        col = line.split()
        if col[0] == "I":
            num, pid = map(int, col[1:3])
            args = z.read(f"{prefix}/tasks/{num:05}.nul").split(b"\0")
            assert args.pop() == b"" and int(args[0]) == pid
            images[num] = (pid, int(args[1]), int(args[2]), list(map(os.fsdecode, args[4:])), col[-1])
        elif col[0] == "R":
            num, pid, ins, enabled, running, status = map(int, col[1:])
            saved_pid, dev, ino, argv, origin = images[num]
            assert pid == saved_pid and origin == "exec" and enabled == running > 0 and ins > 0 and status == 0
            tool, = [t for t in ("rustc", "Wild") if (dev, ino) == (installed[t]["device"], installed[t]["inode"])]
            crate = argv[argv.index("--crate-name") + 1] if "--crate-name" in argv else None
            selected.append({"image": num, "tool": tool, "crate": crate, "instructions": ins, "argv": argv})
        elif col[0] == "W":
            val, en, run, st = map(int, col[1:])
            assert val > 0 and en == run > 0 and st == 0
            whole.append(val)
    projected = json.loads(z.read(prefix + "/physical.json"))
    assert selected == projected["actual"] and whole == [projected["traced_total"]]
    parser, = [r for r in selected if r["crate"] == "ruff_python_parser"]
    producer, = [r for r in selected if r["crate"] == "unicode_names2"]
    assert "--test" in parser["argv"] and "crates/ruff_unicode_names2/src/lib.rs" in producer["argv"]
    assert "-Zlink-only" not in parser["argv"] + producer["argv"] and producer["instructions"] == projected["target_rustc"]
    assert any(r["tool"] == "Wild" for r in selected)
    return sorted(r["crate"] for r in selected if r["crate"]), sum(r["tool"] == "Wild" for r in selected)


def read_block(z, cohort, slot, meta, head, native_dir, executed):
    def get(name):
        return json.loads(z.read(name))
    names = z.namelist()
    assert len(names) == len(set(names)) and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
    bind = get("binding.json")
    assert bind == get("completed.json") and bind["qa"] == head and bind["run"] == str(meta["workflow_run"]["id"])
    assert bind["slot"] == slot and bind["attempt"] == "1" and bind["cohort"] == cohort
    assert bind["order"] == PLAN["schedule"][cohort][slot]
    for field, name in (("worker","worker.py"),("reader","review.py"),("records","records.py"),("registration","registration.json")):
        assert bind[field] == file_hash(HERE / name)
    host = get("host.json")
    assert host["boot"] == bind["boot"] and host["head"] == bind["qa"] and host["order"] == bind["order"]
    assert host["target_case"] == [PLAN["old"], PLAN["new"]] and host["affinity"]
    raw_registry = get("cargo-inputs.json")
    assert raw_registry == BASE["archives"] and len(raw_registry) == 502
    cal = {name:instructions(get("calibrate-" + name + ".json")) for name in ("single", "fork")}
    assert 1.99 < cal["fork"] / cal["single"] < 2.01
    assert z.read("sdk-P/bootstrap.json") == z.read("sdk-C/bootstrap.json")
    blobs, all_counts, native, observed, environments = {}, {}, {}, {}, []
    def blob(sha):
        if sha not in blobs:
            raw = sp.check_output(["zstd", "-qdc"], input=z.read("native/" + sha + ".zst"))
            assert digest(raw) == sha
            blobs[sha] = raw
        return blobs[sha]
    for role in bind["order"]:
        ds = get("installed-" + role + ".json")
        proof, sdk, oracle = (get(f"sdk-{role}/" + n) for n in ("source.json","sdk.json","probes/verdict.json"))
        k = "parent" if role == "P" else "candidate"
        assert proof["source"] == PLAN[k] and proof["tree"] == PLAN[k + "_tree"]
        assert proof["factory"] == PLAN["sdk_origins"][role]["qa"] and str(proof["run"]) == str(PLAN["sdk_origins"][role]["run"])
        assert ds["driver"]["sha256"] == sdk["driver"] == PLAN["sdk_origins"][role]["driver"]
        assert ds["rustc"]["sha256"] == sdk["rustc"]
        assert ds["cargo"]["sha256"] == BASE["release_members"]["bin/cargo"]["sha256"]
        assert ds["Wild"]["sha256"] == next(v["sha256"] for n,v in BASE["release_members"].items() if n.endswith("/ld.bfd"))
        assert PLAN[k] in ds["versions"]["rustc"] and PLAN["cargo"] in ds["versions"]["cargo"]
        assert oracle["marked_arrays"] == (4 if role=="C" else 0) and oracle["native_repaired"] == oracle["native_empty"] != oracle["native_old"]
        counts, elfs, verdicts = {}, {}, []
        for phase in [*PLAN["phases"], "observed-edit"]:
            pre = role + "/" + phase
            inv = get(pre+"/invocation.json")
            src = PLAN["old"] if phase == "old" else PLAN["new"]
            env = inv["env"]
            assert inv["source"] == src and inv["cwd"] == bind["source_root"] and inv["cargo"] == PLAN["command"]
            assert env["CARGO_BUILD_JOBS"] == "2" and env["CARGO_NET_OFFLINE"] == "true"
            assert set(env) <= {"PATH","HOME","USER","LANG","TZ","TMPDIR","RUSTUP_HOME","CARGO_HOME","CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR","CARGO_NET_OFFLINE","CARGO_BUILD_JOBS"}
            assert env["CARGO_BUILD_BUILD_DIR"] != env["CARGO_TARGET_DIR"]
            environments.append(env)
            assert inv["scored_counter"] == (phase in PLAN["priced"])
            if phase in PLAN["priced"]:
                assert len(inv["argv"]) == len(PLAN["command"]) + 3 and Path(inv["argv"][0]).name == "whole_count"
                assert inv["argv"][3:] == PLAN["command"]
                counts[phase] = instructions(get(pre+"/hardware.json"))
            elif phase == "observed-edit":
                assert Path(inv["argv"][0]).name == "exec_count" and inv["argv"][-len(PLAN["command"]):] == PLAN["command"]
            else:
                assert inv["argv"] == PLAN["command"] and pre+"/hardware.json" not in names
            events = [json.loads(raw) for raw in z.read(pre+"/cargo.jsonl").splitlines()]
            bad = phase.startswith("invalid")
            assert int(z.read(pre+"/status")) == (101 if bad else 0)
            assert events[-1] == {"reason":"build-finished","success":not bad}
            raw_input = blob(inv["unicode_source"])
            if bad:
                original = PLAN["bad_input"]
                assert digest(raw_input) == original["invalid_file"] and raw_input.endswith(original["suffix"].encode())
                assert overflow(events) == original["range"]
                a, b = original["range"];assert raw_input[a:b] == b"256"
                verdicts.append(overflow(events))
                continue
            assert inv["unicode_source"] == PLAN["unicode_sources"][src]
            stage = PLAN["rehearsal"]["edit" if phase == "observed-edit" else phase]
            n = get(pre+"/native.json")
            assert n["roster"] == roster(events,bind["source_root"]) == stage["artifacts"]
            test_executable(events)
            assert n["generated"] == stage["generated"] and len(n["generated"]) == 3
            for sha in n["generated"].values(): blob(sha)
            inventory = z.read(pre+"/test-inventory.txt")
            native_checks(inventory,z.read(pre+"/one-test.stdout"),PLAN)
            raw = blob(n["elf"])
            assert raw[:6] == b"\x7fELF\x02\x01" and len(raw) == n["elf_bytes"]
            elfs[phase] = n["elf"]
            if n["elf"] not in executed:
                path = native_dir / n["elf"]
                path.write_bytes(raw);path.chmod(0o700)
                standalone = sp.check_output([path,"--list","--format","terse"],timeout=30)
                actual = sp.check_output([path,"--exact",PLAN["native_test"]],timeout=60)
                assert standalone == inventory
                native_checks(standalone,actual,PLAN);executed.add(n["elf"])
            if phase == "observed-edit":
                observed[role] = read_exec(z,pre,ds)
        assert verdicts == [PLAN["bad_input"]["range"]]*2
        assert len(set(v for k,v in elfs.items() if k!="old")) == 1 and elfs["old"] != elfs["empty"]
        native[role] = {"old":elfs["old"],"new":elfs["empty"],"invalid_ranges":verdicts}
        all_counts[role] = counts
    assert all(e == environments[0] for e in environments)
    assert {"native/"+sha+".zst" for sha in blobs} == {n for n in names if n.startswith("native/") and not n.endswith("/")}
    ratios = {p:1-all_counts["C"][p]/all_counts["P"][p] for p in PLAN["priced"]}
    return {"slot":slot,"boot":bind["boot"],"order":bind["order"],"counts":all_counts,"saving":ratios,
            "artifact":meta["id"],"artifact_sha256":meta["digest"].removeprefix("sha256:"),"bytes":meta["size_in_bytes"],
            "calibration":cal,"native":native,"observed_unscored":observed}


def score(cohort, blocks):
    saves = [b["saving"]["edit"] for b in blocks]
    losses = [p for p in ("old","unchanged","empty") if all(
        b["counts"]["C"][p]-b["counts"]["P"][p] > 10_000_000 and b["saving"][p] < -.05 for b in blocks)]
    if cohort == "pilot":
        good = len(saves) == 2 and all(s >= .05 for s in saves)
    else:
        good = len(saves) == 6 and min(saves)>0 and statistics.median(saves)>=.05
    return {"qualified":good and not losses,"median":statistics.median(saves),"range":[min(saves),max(saves)],
            "consistent_regressions":losses,"all_favorable":min(saves)>0}


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("cohort",choices=PLAN["schedule"]);cli.add_argument("directory",type=Path)
    cli.add_argument("head"); cli.add_argument("run",type=int);cli.add_argument("output",type=Path)
    args=cli.parse_args()
    artifacts=load(args.directory/"artifacts.json")["artifacts"]
    by_name={a["name"]:a for a in artifacts}
    assert len(artifacts)==len(by_name)==len(PLAN["schedule"][args.cohort])
    blocks=[];executed=set()
    with tempfile.TemporaryDirectory() as td:
        for slot in PLAN["schedule"][args.cohort]:
            m=by_name[f"parser-norun-{slot}-{args.run}"]
            assert m["workflow_run"]["id"]==args.run and m["workflow_run"]["head_sha"]==args.head
            fn=args.directory/(str(m["id"])+".zip")
            assert fn.stat().st_size==m["size_in_bytes"] and "sha256:"+file_hash(fn)==m["digest"]
            with zipfile.ZipFile(fn) as z:
                blocks.append(read_block(z,args.cohort,slot,m,args.head,Path(td),executed))
    boots={b["boot"] for b in blocks}
    assert len(boots)==len(blocks) and len({b["artifact"] for b in blocks})==len(blocks)
    if args.cohort=="confirmation":
        pilot=load(HERE/"evidence/pilot/qualified.json")
        assert pilot["qualified"] and pilot["registration"]==file_hash(HERE/"registration.json")
        assert boots.isdisjoint(b["boot"] for b in pilot["blocks"])
    result={"cohort":args.cohort,"registration":file_hash(HERE/"registration.json"),"qa":args.head,
            "run":args.run,"blocks":blocks,"unique_native_executed":sorted(executed),**score(args.cohort,blocks)}
    if args.cohort=="confirmation" and result["all_favorable"]:
        result["two_sided_exact_sign_p"]=2/64
    dump(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ("blocks","unique_native_executed")},indent=2))


if __name__=="__main__":
    main()
