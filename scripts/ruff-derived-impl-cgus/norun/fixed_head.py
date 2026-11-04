"""Registered trained-compiler pair on an uncommitted Ruff change at the original HEAD."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixed_build_script
import fixed_source as s
import pilot as q

b, p = q.b, q.p
HERE = Path(__file__).resolve().parent
plan = q.read_json(HERE / "fixed-plan.json")
OUT = q.OUT
ORDERS = plan["orders"]
SEC = "cargo-artifacts"


def version(exe, directory, state):
    result = p.original(exe, directory, state)
    run = subprocess.run([exe,"version","--output-format","json"],cwd=b.WORK,env=b.env(),capture_output=True,timeout=30)
    value = json.loads(run.stdout)
    b.need(run.returncode == 0 and not run.stderr and value["commit_info"]["commit_hash"] == s.OLD, "unexpected compiled Git identity")
    (directory / "version.stdout").write_bytes(run.stdout)
    return result | {"version":value}


def build_script():
    return fixed_build_script.collect((b.TARGET,b.BUILD),s.OLD,b.WORK/".git/HEAD")


def ordinary(label, state, kind="ordinary"):
    before = s.validate(b.WORK,state)
    native = q.phase(label,state,kind)
    after = s.validate(b.WORK,state)
    b.need(before == after, "source or HEAD changed during command")
    b.put(b.PUB / label / "source.json",after)
    b.put(b.PUB / label / "ruff-build-script.json",build_script())
    if kind == "tasks":
        td = b.PUB / label
        journal = td / "kernel-execs"
        images = []
        for line in (journal / "epochs.tsv").read_text().splitlines():
            f = line.split()
            if f[0] != "I" or f[5] != "exec":
                continue
            fields = (journal / f"{int(f[1]):05}.nul").read_bytes().split(b"\0")
            b.need(fields.pop() == b"" and int(fields[0]) == int(f[2]), "truncated process identity")
            images.append({"pid":int(f[2]), "physical":os.fsdecode(fields[3]), "argv":list(map(os.fsdecode,fields[4:]))})
        b.put(td / "all-executed-images.json", images)
        scripts = [v for v in images if "build-script-build" in Path(v["physical"]).name or "build_script_build" in Path(v["physical"]).name]
        b.put(td / "actual-build-scripts.json",scripts)
    return native


def cargo_artifacts(label, state, normal):
    # This third, unscored, separately initialized history binds Cargo's own "fresh" bit to its real target.
    td = b.PUB / (SEC + "-" + label)
    td.mkdir()
    source = s.validate(b.WORK,state)
    with (td/"stdout").open("xb") as out, (td/"stderr").open("xb") as err:
        run = subprocess.run([*q.CMD, "--message-format=json"],cwd=b.WORK,env=b.env(),stdout=out,stderr=err)
    b.need(run.returncode == 0 and s.validate(b.WORK,state)==source, "Cargo artifact reporter failed")
    rows, roots = [], {}
    cache = b.WORK / "crates/ruff"
    finished = []
    for line in (td/"stdout").read_bytes().splitlines():
        m = json.loads(line)
        if m["reason"] == "build-finished":
            finished.append(m["success"])
        if m["reason"] != "compiler-artifact":
            continue
        t = m["target"]
        r = {"pkg":m["package_id"], "source":t["src_path"], "name":t["name"], "kind":t["kind"],
             "test_profile":m["profile"]["test"], "fresh":m["fresh"], "executable":m["executable"]}
        b.need(isinstance(r["fresh"],bool), "unknown Cargo freshness")
        rows.append(r)
        if r["test_profile"] and r["executable"] is not None and Path(r["source"]).is_relative_to(cache):
            name = Path(r["source"]).relative_to(cache).as_posix()
            f = Path(r["executable"]).resolve(strict=True)
            b.need(name in q.ROOTS and name not in roots and any(f.is_relative_to(x.resolve()) for x in (b.TARGET,b.BUILD)), ("unknown reported test product",name))
            roots[name] = b.hf(f)
    b.need(finished == [True] and roots == {n:v["sha256"] for n,v in normal["roots"].items()} and
           b.hf(b.TARGET / "debug/ruff")==normal["cli"]["sha256"], ("reporter altered tested outputs",label))
    b.put(td/"inventory.json", {"source":source,"reported_artifacts":len(rows),"dirty":[v for v in rows if not v["fresh"]],
          "roots":roots,"linkable_cli":normal["cli"]["sha256"],"build_script_output":build_script()})


def run_role(role, saved, proof):
    b.ROOT.mkdir(); b.guard()
    b.PUB = OUT / role; b.PUB.mkdir()
    sdk,compiled = q.trained.fetch(role, q.CACHE, b.PUB / "factory")
    q.trained.transport.install(sdk,compiled,b.SDK,b.RUSTUP/"toolchains/ohm")
    for name in ("rustc","cargo"):
        b.need(subprocess.check_output([name,"+ohm","-vV"],env=b.env(),text=True)==compiled["versions"][name], "unexpected physical toolchain")
    for name in ("whole_count","exec_count"):
        subprocess.run(["cc","-O2","-pthread","-Wall","-Wextra","-Werror",p.frozen/(name+".c"),"-o",b.ROOT/name],check=True)
    b.verdict = version
    b.put(b.PUB/"old-source.json",s.validate(b.WORK,s.OLD,full=True))
    b.prepare()
    old = ordinary("cold-old",s.OLD)
    q.same(old,ordinary("old-unchanged",s.OLD),"settled OLD")
    initial_output = build_script()
    b.put(b.PUB/"edited-buffers.json",s.apply(b.WORK))
    edited = ordinary("edit",s.NEW)
    b.put(b.PUB/"build-script-edit.json", {"old":initial_output,"edited":build_script()})
    b.need({n:v["inventory"] for n,v in old["roots"].items()} == {n:v["inventory"] for n,v in edited["roots"].items()}
           and old["cli"] != edited["cli"] and old["verdict"] != edited["verdict"], "missing actual source-specific native change")
    q.same(edited,ordinary("new-unchanged",s.NEW),"settled working-tree edit")
    q.invalid()
    q.same(edited,ordinary("repair",s.NEW),"repaired native output")
    p.empty_outputs(); b.prepare()
    q.same(edited,ordinary("empty-new",s.NEW),"independent empty native output")
    p.empty_outputs()
    b.put(b.PUB/"restored-source.json",p.old_namespace.restore_checkout(b.WORK,saved,proof))
    b.prepare()
    q.same(old,ordinary("second-cold-old",s.OLD),"second independent OLD")
    q.same(old,ordinary("observed-old-unchanged",s.OLD,"tasks"),"observed settled OLD")
    b.put(b.PUB/"repeated-edited-buffers.json",s.apply(b.WORK))
    q.same(edited,ordinary("observed-edit",s.NEW,"tasks"),"observed ordinary edit")
    q.same(edited,ordinary("observed-new-unchanged",s.NEW,"tasks"),"observed settled edit")
    p.empty_outputs()
    p.old_namespace.restore_checkout(b.WORK,saved,proof)
    b.prepare()
    cargo_artifacts("cold-old",s.OLD,old)
    cargo_artifacts("old-unchanged",s.OLD,old)
    s.apply(b.WORK)
    cargo_artifacts("edit",s.NEW,edited)
    cargo_artifacts("new-unchanged",s.NEW,edited)
    b.put(b.PUB/"complete.json", {"all_controls":True,"role":role,"content":s.NEW,"head":s.OLD,"ordinary":q.CMD})
    p.empty_outputs()
    b.need(b.ROOT.name=="ohm-clap-cli" and b.ROOT.parent==OUT.parent and not b.ROOT.is_symlink(),"unknown transient root")
    shutil.rmtree(b.ROOT)


def main():
    slot = int(os.environ["BOOT_SLOT"])
    branch = os.environ["GITHUB_REF_NAME"]
    b.need(0 <= slot < len(ORDERS) and branch == plan["branch"] and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and
           os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"] and b.git("rev-parse","HEAD")==s.NEW and
           b.git("rev-parse","HEAD^")==s.OLD and b.hf(HERE/"pilot.py")==plan["original_native_receiver"],"unregistered source worker")
    OUT.mkdir()
    b.put(OUT/"registration.json", {"plan":plan, "factory":q.trained.spec,"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
          "receiver":os.environ["REVIEWED_HEAD"], "slot":slot, "order":ORDERS[slot]})
    b.select(s.OLD)
    saved = OUT.parent / "original-ruff-checkout"
    proof = p.old_namespace.save_checkout(b.WORK,saved)
    b.put(OUT/"source-original.json",proof)
    errors = {}
    for n,role in enumerate(ORDERS[slot]):
        if n:
            p.old_namespace.restore_checkout(b.WORK,saved,proof)
        try:
            run_role(role,saved,proof)
        except Exception as error:
            errors[role] = repr(error)
            b.put(OUT/("refusal-"+role+".json"),{"reason":repr(error)})
            print(role,repr(error),flush=True)
            if b.ROOT.is_dir(): b.ROOT.rename(OUT.parent/("refused-fixed-"+role))
    if errors: raise RuntimeError(errors)
    def inventory(role):
        td = OUT/role
        return {"edited_rustc_link":sorted((x["kind"],x.get("source"),x.get("link_only",False)) for x in q.read_json(td/"observed-edit/task-instructions.json")),
                "cargo_dirty":sorted((x["source"], x["name"], tuple(x["kind"]), x["test_profile"]) for x in q.read_json(td/(SEC+"-edit")/"inventory.json")["dirty"]),
                "runtime": {k:q.read_json(td/k/"native.json")["verdict"] for k in ("cold-old","edit","repair","empty-new")},
                "test_inventory": {n:x["inventory"] for n,x in q.read_json(td/"edit/native.json")["roots"].items()}}
    b.need(inventory("P")==inventory("C"),"different native verdict or selected work")
    b.put(OUT/"terminal.json", {"ordinary":q.CMD,"order":ORDERS[slot],"all_cases":True})


if __name__ == "__main__":
    main()
