"""Reopen a complete host's native, type, disk and whole-command counter evidence. Score only a full pair."""
import argparse
from collections import Counter
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import os

HERE=Path(__file__).resolve().parent
os.environ.setdefault("RUNNER_TEMP",tempfile.gettempdir())
sys.path.insert(0,str(HERE))
import screen as s
import graph
import witness as q
import guard
import boot_identity as boots
from selection import roster

need=graph.need


def read(p):
    return q.read_gz(p) if p.suffix==".gz" else json.loads(p.read_bytes())


def calibrated(logs,calibrator,observers):
    spec=importlib.util.spec_from_file_location("integration_calibration_readback",s.IPMU/"verify.py")
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m.calibrate(logs,calibrator,observers)


def client(d, expected, owner, branch, visible):
    need(set(expected)=={"layout-64","layout-56"},"missing or extra typed-client verdict")
    for size in (64,56):
        label="layout-"+str(size)
        cmd=read(d/(label+".command.json")); args=cmd["argv"]
        need(args[:7]==["rustc","+ohm","--crate-name","root_checked","--crate-type=lib","--edition=2024","--emit=metadata"] and
             args[7]=="--error-format=json" and args[8]==str(visible.parent/"typed-client/reader.rs") and
             args[-2:]==["-o",str(visible.parent/"typed-client/libroot_checked.rmeta")],"changed metadata client")
        need(args[9:-2]==[v for n in graph.PROVIDERS for v in ("--extern",n+"="+owner["providers"][n])]+[v for opt in owner["search"] for v in ("-L",opt)],"extra or reordered arguments to typecheck")
        externs=[v for i,v in enumerate(args) if i and args[i-1]=="--extern"]
        dirs=[v for i,v in enumerate(args) if i and args[i-1]=="-L"]
        need(externs==[n+"="+owner["providers"][n] for n in graph.PROVIDERS] and dirs==owner["search"],"wrong actual extern")
        raw=gzip.decompress((d/(label+".stderr.gz")).read_bytes())
        need(not gzip.decompress((d/(label+".stdout.gz")).read_bytes()) and cmd["source_sha256"]==
             hashlib.sha256((HERE/"reader.rs").read_bytes().replace(b"EXPECTED",str(size).encode())).hexdigest(),"unbound consumer source")
        if size==q.SIZE[branch]:
            file=d/(label+".rmeta")
            need(cmd["code"]==0 and not raw and expected[label]=={"status":0,"body":[file.stat().st_size,q.file_sha(file)]} and
                 file.stat().st_size>1024,"changed positive metadata")
        else:
            diag=[json.loads(l) for l in raw.splitlines()]
            q.type_error(diag,"EXPRESSION_BYTES",{str(visible.parent/"typed-client/reader.rs")})
            need(cmd["code"]==1 and not (d/(label+".rmeta")).exists() and expected[label]=={"status":1,"diagnostics":graph.digest(diag)},
                 "different opposite-size rejection")


def authenticated_sdk(path,manifest):
    expected=manifest["files"]["F"]
    actual=s.b.inventory(path)
    need(len(expected)==81 and {p:[f[0],f[4],f[3]] for p,f in actual.items()}==expected,"independent F metadata decoder is not the complete authenticated SDK")
    return path/"bin/rustc"


def provider_records(observed, messages, directory, visible):
    own=observed["owner"];records=observed["providers"];files=observed["files"]
    need(set(records)==set(own["providers"])==set(graph.PROVIDERS),"incomplete or extra observed or physical provider")
    for cls in graph.PROVIDERS:
        p=Path(own["providers"][cls]);rel=str(p.relative_to(visible));record=records[cls]
        matches=[m for m in messages if m["reason"]=="compiler-artifact" and m["target"]["name"]==cls and str(p) in m["filenames"]]
        need(len(matches)==1 and record=={"relative":rel,"file":files[rel],"features":matches[0]["features"],"profile":matches[0]["profile"]} and
             p.name.startswith("lib"+cls+"-") and p.suffix==".rmeta" and files[rel][0]>1024 and (directory/(files[rel][1]+".zst")).is_file(),
             "wrong real provider, feature/profile, path or body")


def reopen_listings(d,owners,providers,body_dir,decoder):
    need(set(owners)==set(providers)==set(graph.PROVIDERS),"listing provider omitted")
    for pattern in (".metadata-listing.gz",".metadata-listing-stderr.gz",".metadata-command.json"):
        need({x.name for x in d.glob("*"+pattern)}=={n+pattern for n in graph.PROVIDERS},"absent or unexpected metadata listing files")
    with tempfile.TemporaryDirectory() as td:
        for name in graph.PROVIDERS:
            src=Path(owners[name]);cert=providers[name]["file"];f=Path(td)/src.name
            raw,err=[gzip.decompress((d/(name+suffix)).read_bytes()) for suffix in (".metadata-listing.gz",".metadata-listing-stderr.gz")]
            command=read(d/(name+".metadata-command.json"))
            need(q.listing(name,src,cert,raw,err,command["status"])==command,"original native metadata command or streams differ")
            with f.open("xb") as dst:subprocess.run(["zstd","-dcq",body_dir/(cert[1]+".zst")],stdout=dst,check=True)
            need([f.stat().st_size,q.file_sha(f)]==cert,"complete retained metadata input differs")
            run=subprocess.run([decoder,"-Zls=root",f],env={"PATH":os.defpath,"LC_ALL":"C","LD_LIBRARY_PATH":str(decoder.parent.parent/"lib")},capture_output=True,timeout=120)
            need((run.returncode,run.stdout,run.stderr)==(command["status"],raw,err),"independent exact F decoder output differs")
            f.unlink()


def worker(logs,calibrator,observers,sdk_path):
    en=read(logs/"enrollment.json");end=read(logs/"complete.json");p=en["position"]
    boot=en["boot"];visible=Path(en["visible_work"])
    need(end["qualified"] and end["head"]==en["head"] and end["position"]==p and end["boot"]==boot and en["attempt"]==1 and
         en["order"]==s.ORDERS[p] and en["argv"]==graph.CARGO and en["plan"]==q.file_sha(HERE/"PLAN.md") and
         en["selection"]==graph.census(s.EXPECTED) and boot not in boots.prior(),"different enrollment")
    admitted=read(logs/"admission-capacity.json")
    capacity=[json.loads(line) for line in (logs/"capacity.jsonl").read_text().splitlines()]
    need(en["source"]==s.b.spec() and guard.checked(admitted) and guard.passes(admitted,(12,14,32)) and capacity and
         all(guard.checked(row) and row["cgroup_leaf"]==admitted["cgroup_leaf"] and guard.passes(row,(5,3,6)) for row in capacity),
         "insufficient, missing or inconsistent host resource evidence")
    manifest=read(logs/"sdk/manifest.json");sdk=read(logs/"sdk/F.json");inp=read(logs/"ruff-inputs.json")
    need(q.file_sha(logs/"sdk/manifest.json")==s.b.spec()["manifest"] and read(logs/"source-kit.json")==s.b.spec() and
         manifest["roles"]["F"]["commit"]==s.b.HEADS["F"] and manifest["strict_cargo"]==s.b.CARGO and manifest["wild"]==s.b.WILD_ELF and
         sdk["source_commit"]==s.b.HEADS["F"] and sdk["compiler_tree"]==s.b.COMPARE["F"] and
         len(sdk["files"])==81 and sdk["files"][sdk["driver"]][0]=="fe62e729ee976d9b808b4f94f0a9751c7f6d7b2201aecf3636e9eff8acb88273" and
         inp["lock"]=="839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb" and len(inp["archives"])==505 and len(inp["changed"])==169,
         "wrong physical tools or historical source")
    decoder=authenticated_sdk(sdk_path,manifest)
    ready=read(logs/"meter-ready.json");cal=calibrated(logs,calibrator,observers)
    need(cal["boot"]==boot==ready["boot"] and cal["cells"]==28,"wrong or uncalibrated boot")
    need(s.tr.controls(logs/"initial/kernel-events")==read(logs/"initial/kernel-events/calibration.json")["proof"],"native tracer controls")
    q.verify_bodies(logs/"complete-bodies")
    actual,refs,errors={},{},{};previous=0
    counts=Counter();zips={}
    for arm in en["order"]:
        for br in "AB":
            d=logs/"graphs"/arm/br
            u,m=[json.loads(gzip.decompress((d/(n+".stdout.gz")).read_bytes())) for n in ("unit","members")]
            need(graph.selection(u,m,Path(m["workspace_root"]))==s.EXPECTED,"graph bytes differ")
    structure={}
    for lane,arms in [("empty",en["order"]),("structure",en["order"][:1]),("measured",en["order"])]:
        for arm in arms:
            base=logs/lane/arm;role=read(base/"arm.json");env=role["env"]
            need(role["source_manifest"]==en["source"]["manifest"]==s.b.spec()["manifest"] and role["arm"]==arm and
                 role["files"]=={n:sdk["files"][n] for n in ("bin/cargo","bin/rustc","bin/rustdoc",sdk["driver"],s.b.WILD)} and
                 (env.get("CARGO_ENCODED_RUSTFLAGS")=="-Zohm-branch-cache=yes")==arm.endswith("on"),"role or injector")
            if lane=="measured":actual[arm]={}
            phases=[("A","A"),("B","B"),("invalid","B"),("repair","B")] if lane=="empty" else s.w.PHASES
            for name,br in phases:
                d=base/name;r=read(d/"visit.json");cmd=read(d/"cargo.json.gz");source=read(d/"source.json");rc=101 if name=="invalid" else 0
                need(r["arm"]==arm and r["branch"]==br and r["exit"]==cmd["exit"]==rc and r["pass"] and
                     cmd["argv"]==graph.CARGO and cmd["env"]==env and source["commit"]==inp["commits"][br] and source["tree"]==inp["trees"][br] and
                     source["registry_lock"]==inp["lock"] and source["status"]==("M crates/ruff_python_parser/src/lib.rs" if rc else ""),
                     "wrong actual source or requested command")
                q.source_check(source,bool(rc))
                need(source["branch"]=="refs/heads/"+s.kit.NAMES[br],"different branch identity")
                stdout,stderr=[gzip.decompress((d/("cargo."+k+".gz")).read_bytes()) for k in ("stdout","stderr")]
                need(cmd["stdout_sha256"]==hashlib.sha256(stdout).hexdigest() and cmd["stderr_sha256"]==hashlib.sha256(stderr).hexdigest(),"original Cargo bytes")
                msgs=[json.loads(l) for l in stdout.splitlines()];cwd=Path(cmd["cwd"])
                need(msgs[-1]=={"reason":"build-finished","success":not rc},"wrong Cargo terminal")
                clock=None;phys=None
                if lane!="measured":
                    proof,raw,_=s.tr.checked_replay(d);phys=read(d/"native-execs.json.gz")
                    import io
                    events=s.w.processes.execs(io.StringIO(raw.decode()))
                    identities=read(d/"exec-inodes.json.gz");native=s.native.read(events,identities,Path(role["sdk"]),role["files"],s.b.WILD,
                       visible.parent/"home/.cargo/bin/rustup",read(logs/"sdk/proxy.json"))
                    need(not (d/"clock.json").exists() and not r["instructions"] and proof["installed_images"]==len(events) and
                         native==phys and phys["cargos"][0]["argv"][1:]==graph.CARGO[2:] and s.native.counts(native)==r["execs"],
                         "missing, extra or wrongly classified physical compiler, query, linker or image count")
                    counts["traced"]+=1
                    if lane=="structure":structure[name]=r["execs"]
                else:
                    clock=s.w.clock(d/"clock.json",rc)
                    need(r["before_cargo"]<=clock["start"]<clock["stop"]<=r["after_cargo"]<=r["after_output_checks"] and
                         clock["start"]>previous and r["instructions"]==clock["instructions"] and
                         cmd["observer_argv"]==[ready["plain"],str(visible.parent/"logs/measured"/arm/name/"clock.json"),*graph.CARGO] and
                         not (d/"exec.raw.gz").exists(),"instrumentation or oracle in measured interval")
                    previous=clock["stop"];counts["measured"]+=1
                    actual[arm][name]=clock|{"allocated":r["allocated"]}
                    need(end["rows"][arm][[x[0] for x in s.w.PHASES].index(name)]==r,"wrong terminal rows")
                ino=read(d/"path-inodes.json.gz");pairs={}
                for dev,inum,links,mode,blocks,size in ino.values():
                    need(pairs.setdefault((dev,inum),blocks)==blocks,"inconsistent physical aliases")
                need(512*sum(pairs.values())==read(d/"storage.json")["allocated"]==r["allocated"],"unreconciled physical allocation")
                diag=q.diagnostics(msgs)
                if rc:
                    q.error_check(diag,cwd)
                    need(read(d/"observed-errors.json.gz")==diag and errors.setdefault(arm,diag)==diag,"different genuine compiler diagnostic")
                    continue
                orig=read(d/"observed.json.gz");files=orig["files"]
                need(all(m["filenames"] for m in msgs if m["reason"]=="compiler-artifact") and graph.typed_graph(msgs,s.EXPECTED,cwd)==orig["units"] and
                     set(files)=={str(Path(p).relative_to(visible)) for m in msgs if m["reason"]=="compiler-artifact" for p in m["filenames"]}|{orig["typeshed_file"]} and
                     orig["diagnostics"]==diag and read(d/"differences.json.gz")=={},"incomplete files, warning stream or raw product difference")
                typed,dirty=roster(msgs,cwd)
                reported=read(d/"artifact-paths.json.gz")
                need(orig["typed"]==typed and orig["dirty"]==dirty and
                     orig["scripts"]==sorted((m for m in msgs if m["reason"]=="build-script-executed"),key=graph.encoded) and
                     reported=={p:f for p,f in files.items() if p!=orig["typeshed_file"]} and
                     all(Path(p).parts[0] in ("build","target") and ".." not in Path(p).parts for p in files),"edited typed roster or unbound recorded file")
                own=orig["owner"]
                is_reference=lane=="empty" and name in {"A","B"}
                if is_reference or (phys and any(row["crate"]=="ruff_dev" and row["mode"]=="full" for row in phys["rustcs"])):
                    need(phys and s.q.owner(phys,cwd,visible,arm)==own,"absent or unbound actual dirty ruff_dev compiler")
                provider_records(orig,msgs,logs/"complete-bodies",visible)
                if is_reference:reopen_listings(d,own["providers"],orig["providers"],logs/"complete-bodies",decoder)
                zip_hash=files[orig["typeshed_file"]][1]
                if zip_hash not in zips:
                    with tempfile.TemporaryDirectory() as td:
                        f=Path(td)/"zipped_typeshed.zip"
                        with f.open("xb") as dst:subprocess.run(["zstd","-dcq",logs/"complete-bodies"/(zip_hash+".zst")],stdout=dst,check=True)
                        zips[zip_hash]=q.read_typeshed(f)
                need(zips[zip_hash]==orig["typeshed"],"changed generated typeshed bytes or member identity")
                client(d,orig["client"],own,br,visible)
                if lane=="empty" and name in "AB":
                    need(all(not m["fresh"] for m in msgs if m["reason"]=="compiler-artifact"),"warm independent empty")
                    refs[arm,br]=orig
                else:
                    ref=refs[arm,br]
                    need(all(orig[k]==ref[k] for k in ("files","providers","typeshed","typeshed_file","client","scripts","typed","diagnostics")) and
                         all(own[k]==ref["owner"][k] for k in ("providers","search")),"empty reference or reader fields differ")
    need(counts=={"traced":15,"measured":14} and len(structure)==7 and errors["Foff"]==errors["Fon"],"incomplete native/counter census")
    return {"verified":True,"run":en["run"],"head":en["head"],"position":p,"order":en["order"],"boot":boot,
            "calibration":cal,"storage_mode":(logs/"storage-mode.txt").read_text().strip(),"resource_minima":{k:min(row[k] for row in capacity) for k in ("available_memory","work_free","durable_free")},"selection":en["selection"],"counts":dict(counts),"native":structure,"all":actual}


def decide(first,second,e_ledger):
    by={r["position"]:r for r in (first,second)}
    need(set(by)==set(s.ORDERS) and len({r["boot"] for r in by.values()})==2 and len({(r["run"],r["head"]) for r in by.values()})==1 and
         len({graph.digest(r["selection"]) for r in by.values()})==1 and
         len({graph.digest([r["calibration"]["cpu"],r["calibration"]["pmu"]]) for r in by.values()})==1 and all(r["verified"] and r["order"]==s.ORDERS[p] for p,r in by.items()),"not two mirrored fresh hosts")
    e_boot_ids=boots.validate(e_ledger,{r["boot"] for r in by.values()})
    rows={}
    for p,r in sorted(by.items()):
        values={name:[r["all"][a][name]["instructions"] for a in ("Foff","Fon")] for name,br in s.w.PHASES}
        need(all(type(v) is int and v>0 for pair in values.values() for v in pair),"incomplete raw integers")
        for name,what in (("both-returns",("return-A","return-B")),("first-switch-plus-return",("first-B","return-A")),
                          ("cold-through-returns",("cold-A","first-B","return-A","return-B")),("all-seven",tuple(values))):
            values[name]=[sum(values[k][i] for k in what) for i in (0,1)]
        rows[p]={"per_phase_clock_and_allocation":r["all"],"raw":values,"off_on":{k:float(Fraction(*v)) for k,v in values.items()}}
    return {"disjoint_prior_boots":len(boots.prior()),"disjoint_corrected_E_run":boots.RUN,"disjoint_corrected_E_boots":len(e_boot_ids),"screen_pass":all(x["raw"][n][0]>2*x["raw"][n][1] for x in rows.values() for n in ("return-A","return-B","both-returns")),"hosts":rows}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="mode",required=True)
    x=sub.add_parser("worker");x.add_argument("logs",type=Path);x.add_argument("calibrator",type=Path);x.add_argument("observers",type=Path);x.add_argument("sdk",type=Path)
    a=p.parse_args();print(json.dumps(worker(a.logs,a.calibrator,a.observers,a.sdk.resolve()),sort_keys=True))
