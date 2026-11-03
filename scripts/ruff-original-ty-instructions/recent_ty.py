"""Unscored, signed -23 native census on Ruff's debug-information snapshot edit."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/"ruff-foreign-span-observer"))
import worker as w
OLD="157caa55a51ebae4fa541d31697e3af9a6c32ccf"
NEW="bfa2407e98ee1343caeefd02b4b69043509baa8c"
LOCK="b9cbcf372621bf3aa25ba0985e0b066b8c70624d51ecc50cc2f29b98712e6f40"
cmd=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j4","--message-format=json"]
assert os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"] and os.environ["GITHUB_RUN_ATTEMPT"]=="1"
assert w.git("rev-parse","HEAD")==NEW and w.git("rev-parse","HEAD^")==OLD and w.hf(w.work/"Cargo.lock")==LOCK
w.put(w.proof/"registration.json",dict(old=OLD,edited=NEW,lock=LOCK,command=cmd,sdk=w.hf(w.src/"sdk.json"),
  scope="Signed stock baseline. Actual old-on-new debug_command refusal, clean and repaired ELF, and an invalid source guard; inspect real changed, unchanged, reverse-edit and re-edit execs. Discovery only."))
env=w.install()
whole,trace=(w.root/v for v in ("whole_count","exec_count"))
for exe in (whole,trace):sp.run(["cc","-O2","-Wall","-Wextra","-Werror",here/(exe.name+".c"),"-o",exe],check=True)
def select(state):
    w.git("switch","--detach",state)
    assert w.hf(w.work/"Cargo.lock")==LOCK and not w.git("status","--porcelain")
def prepare():
    assert all(not p.exists()for p in(w.target,w.shared,w.home))
    env.pop("CARGO_NET_OFFLINE",None)
    sp.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
    env["CARGO_NET_OFFLINE"]="true"
def preserve(exe):
    digest=w.hf(exe);dest=w.proof/(digest+".elf.zst")
    if not dest.exists():
        with dest.open("xb")as f:sp.run(["zstd","-qc","-3",exe],stdout=f,check=True)
    return digest
def verdict(exe,tag,expected):
    td=w.proof/tag;td.mkdir()
    e=dict(env,INSTA_UPDATE="no",CI="true")
    p=sp.run([exe,"--list"],cwd=w.work/"crates/ty_server",env=e,capture_output=True,check=True)
    assert not p.stderr
    names=sorted(x.removesuffix(": test") for x in p.stdout.decode().splitlines() if x.endswith(": test"))
    name,=[n for n in names if n.endswith("::debug_command")]
    assert len(names)==len(set(names))>70
    (td/"test-list").write_bytes(p.stdout)
    res=sp.run([exe,"--exact",name,"--nocapture"],cwd=w.work/"crates/ty_server",env=e,capture_output=True,timeout=90)
    (td/"stdout").write_bytes(res.stdout);(td/"stderr").write_bytes(res.stderr)
    assert res.returncode==expected and (b"1 passed;" if expected==0 else b"1 failed;") in res.stdout,(tag,res.returncode,res.stdout[-600:],res.stderr[-400:])
    if expected:assert b"snapshot" in res.stderr.lower()+res.stdout.lower() and b"debug_command" in res.stderr+res.stdout
    return names
def receipt(tag,kind="whole"):
    w.guard();td=w.proof/tag;td.mkdir()
    if kind=="census":
        (td/"tasks").mkdir();actual=[trace,td/"tasks",*cmd]
    else:actual=[whole,td/"hardware.json",shutil.which("cargo",path=env["PATH"]),*cmd]
    with (td/"stdout.jsonl").open("xb")as o,(td/"stderr").open("xb")as e:p=sp.run(actual,cwd=w.work,env=env,stdout=o,stderr=e)
    assert p.returncode==0,(tag,(td/"stderr").read_text()[-500:])
    msgs=list(map(json.loads,(td/"stdout.jsonl").read_bytes().splitlines()))
    assert msgs[-1]=={"reason":"build-finished","success":True}
    arts=[v for v in msgs if v["reason"]=="compiler-artifact"]
    row,=[v for v in arts if v["target"]["name"]=="e2e" and v["target"]["kind"]==["test"]]
    exe=Path(row["executable"])
    data=dict(commit=w.git("rev-parse","HEAD"),units=sorted([v["package_id"],v["target"]["name"],v["target"]["kind"],sorted(v["features"])]for v in arts),
              dirty=sorted([v["package_id"],v["target"]["name"]]for v in arts if not v["fresh"]),elf=preserve(exe),executable=str(exe))
    if kind=="census":
        def identity(path):
            stat=path.stat()
            return stat.st_dev,stat.st_ino
        rustc=identity(w.sdk/"bin/rustc");wild=identity(w.sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")
        rows=(td/"tasks/epochs.tsv").read_text().splitlines(); epochs={}; totals=collections.Counter(); roster=[]
        for line in rows:
            f=line.split()
            if f[0]=="I":
                args=(td/"tasks"/f"{int(f[1]):05}.nul").read_bytes().split(b"\0");path=Path(os.fsdecode(args[3]))
                key=tuple(map(int,args[1:3]))
                crate=args[args.index(b"--crate-name")+1].decode() if key==rustc and b"--crate-name" in args[4:-1] else None
                owner="rustc:"+crate if crate else path.name
                if crate or key==wild:roster.append(owner)
                epochs[f[1]]=owner
            if f[0]=="C":
                assert int(f[4])>=0 and int(f[5])==int(f[6]);totals[epochs[f[1]]]+=int(f[4])
        data.update(actual=roster,by_executable=dict(totals))
        marker=b"/dev/null/ohm-untracked-relink-inputs:"
        for root in (w.target,w.shared):
            for dep in root.rglob("*.d"):
                if dep.is_file() and marker in dep.read_bytes().splitlines():
                    out=td/"marked-depfiles"/root.name/dep.relative_to(root);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(dep,out)
    else:
        hw=json.loads((td/"hardware.json").read_bytes());assert hw["instructions"]>0 and hw["enabled"]==hw["running"]>0 and hw["status"]==0
        data["instructions"]=hw["instructions"]
    w.put(td/"result.json",data);return exe,data
def price(tag,kind="whole"):
    exe,data=receipt(tag,kind); names=verdict(exe,tag+"-verdict",0)
    return exe,data,names
select(OLD);prepare()
exe,first,inventory=price("old");held=w.root/"original-OLD";shutil.copy2(exe,held)
select(NEW);assert verdict(held,"stale-OLD-on-NEW",101)==inventory
_,edited,names=price("edit");assert names==inventory
_,warm,names=price("first-unchanged");assert names==inventory
_,census,names=price("unchanged-observed","census");assert names==inventory
source=w.work/"crates/ty_server/src/session.rs";orig=source.read_bytes()
try:
    source.write_bytes(orig+b'\nconst _: u8 = "invalid";\n')
    p=sp.run(cmd,cwd=w.work,env=env,capture_output=True)
    (w.proof/"invalid.stdout").write_bytes(p.stdout);(w.proof/"invalid.stderr").write_bytes(p.stderr)
    assert p.returncode==101 and b'"E0308"' in p.stdout and json.loads(p.stdout.splitlines()[-1])=={"reason":"build-finished","success":False}
finally:source.write_bytes(orig)
_,repaired,names=price("repair");assert names==inventory
for directory in (w.target,w.shared,w.home):
    assert directory.is_dir() and not directory.is_symlink();directory.rename(w.root/("parked-"+directory.name))
prepare();_,clean,names=price("independent-NEW");assert names==inventory
select(OLD);_,reverted,names=price("reverse-edit-observed","census");assert names==inventory
select(NEW);_,again,names=price("edit-again-observed","census");assert names==inventory
assert first["elf"]!=edited["elf"] and all(x["units"]==first["units"]for x in(edited,warm,census,repaired,clean,reverted,again))
assert len({x["elf"]for x in(edited,warm,census,repaired,clean,again)})==1 and reverted["elf"]==first["elf"]
assert not w.git("status","--porcelain")
w.put(w.proof/"accepted-current.json",{"first_unchanged":warm["instructions"],"edit":edited["instructions"],"actual_unchanged":census["actual"],"remaining":census["by_executable"],"test_count":len(inventory),"changed":edited["elf"],"old":first["elf"]})
