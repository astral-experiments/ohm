"""Recompute native results from the archived kernel, Cargo, executable and PMU records."""
import collections
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess as sp
import sys
import tempfile
import zipfile

here = Path(__file__).resolve().parent
source = Path(sys.argv[1]) / "scripts/ruff-original-ty-instructions"
sys.path.insert(0, str(source))
import native_qualification as verify
reg = json.loads((source / "native-asm-registration.json").read_bytes())
store = here / "objects"
store.mkdir(exist_ok=True)
old = "710c60f7135879b05f6c05a34085cd7af5c19e7f"
new = "b00f68a23cedbd3a38fc25bac63638f0f11fc3f0"
phases = ("old", "edit", "settled", "sample-0", "sample-1", "sample-2", "census",
          "shadow-repair", "source-repair", "independent-clean")
scored = ("edit", "settled", "sample-0", "sample-1", "sample-2")
command = ["cargo", "+ohm", "build", "-p", "ruff", "--bin", "ruff", "--locked", "--offline", "-j4", "--message-format=json"]
parent_roster = "portable_atomic ruff ruff ruff_db ruff_graph ruff_index ruff_linter ruff_python_ast ruff_python_codegen ruff_python_formatter ruff_python_index ruff_python_literal ruff_python_parser ruff_python_semantic ruff_server ruff_workspace salsa ty_python_semantic".split()
case = "/home/runner/work/ohm/ohm/case.py"
def digest(f):
    with f.open("rb") as s:
        return hashlib.file_digest(s, "sha256").hexdigest()
def write(path, o):
    path.write_text(json.dumps(o, sort_keys=True, indent=2) + "\n")
def physical(z, name):
    key = name.split(".")[0]
    assert re.fullmatch("[a-f0-9]{64}", key) and name in (key + ".native.zst", key + ".rmeta.zst")
    dest = store / key
    with tempfile.TemporaryDirectory(dir=here) as tmp:
        packed, body = Path(tmp) / "packed", Path(tmp) / "original"
        with z.open(name) as src, packed.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        with body.open("xb") as dst:
            sp.run(["zstd","-dq","-c",packed], stdout=dst, check=True)
        assert digest(body) == key
        if dest.exists():
            assert body.stat().st_size == dest.stat().st_size
        else:
            body.rename(dest)
    return key
def probe(exe):
    result = []
    exe.chmod(0o755)
    for deco, expr, key in [("attr.define","attr.field(factory=list)","field"),("attr.attributes","list()","attributes"),
                           ("attr.define","list()","common"),("attr.define","1","clean")]:
        payload = f"import attr\n@{deco}\nclass Example:\n    value: list[int] = {expr}\n"
        p = sp.run([exe, "check", "--isolated", "--no-cache", "--select", "RUF009", "--output-format", "json",
                    "--stdin-filename", case, "-"], input=payload, text=True, capture_output=True, timeout=30)
        assert p.returncode in (0, 1) and not p.stderr
        result.append([key, p.returncode, json.loads(p.stdout)])
    return result
def archive(a, z):
    parse = lambda k: json.loads(z.read(k))
    assert parse("registered.json") == reg
    boot = parse("boot.json")
    pair = a["pair_seen"]
    assert boot["pair"]==pair and boot["order"]==reg["pairs"][pair] and boot["machine"]=="x86_64"
    assert boot["head"]==a["workflow_run"]["head_sha"] and boot["attempt"]=="1" and int(boot["run"])==a["workflow_run"]["id"]
    assert re.fullmatch("[0-9a-f-]{36}",boot["boot_id"])
    for label,code in [("true",0),("false",1)]:
        hw=parse("calibration-"+label+".json")
        assert os.waitstatus_to_exitcode(hw["status"])==code and hw["instructions"]>0 and hw["enabled"]==hw["running"]>0
    persisted={physical(z,k) for k in z.namelist() if k.endswith(".zst")}
    rosters={}; binaries={}; counts={}; cohorts={}; common_units=None;common_diag=None; portable=set()
    for role in "PC":
        counts[role]={}; binaries[role]={}
        hold=parse(role+"-holdouts.json")
        for name,needle in [("invalid-Ruff-source",b"E0308"),("malformed-shadow",b"libm.so")]:
            tag=role+"-"+name+"/"
            raw=z.read(tag+"stdout")
            assert json.loads(raw.splitlines()[-1]) == {"reason":"build-finished","success":False}
            assert needle in raw+z.read(tag+"stderr")
        assert hold["source"]==hold["native"]=={"code":101,"failed":True}
        path=hold["shadow_directory"]; cohort,=re.findall(r'v2-[0-9a-f]{16}',path)
        cohorts[role]={"cohort":cohort,"native_build":str(Path(path).parent)}
        link=parse(role+"-link-inputs.json")
        assert link["jemalloc"]["sha256"]==hold["library"] and hold["library"] in persisted
        with (store/hold["library"]).open("rb") as f: assert f.read(8)==b"!<arch>\n"
        for phase in phases:
            tag=role+"-"+phase+"/"; receipt=parse(tag+"result.json")
            assert receipt["role"]==role and receipt["label"]==phase and receipt["command"]==command
            assert receipt["source"]==(old if phase=="old" else new)
            rows=list(map(json.loads,z.read(tag+"stdout.jsonl").splitlines()))
            assert rows[-1]=={"reason":"build-finished","success":True}
            arts=[r for r in rows if r["reason"]=="compiler-artifact"]
            units=sorted([x["package_id"],x["target"]["name"],x["target"]["kind"],sorted(x["features"])]for x in arts)
            diagnostics=collections.Counter((r["package_id"],r["message"]["level"],r["message"]["message"]) for r in rows if r["reason"]=="compiler-message")
            assert receipt["units"]==units and len(units)==350
            if common_units is None: common_units,common_diag=units,diagnostics
            assert units==common_units and common_diag==diagnostics
            dirty=sorted([x["package_id"],x["target"]["name"]]for x in arts if not x["fresh"])
            assert dirty==receipt["dirty"] and (phase not in ("old","independent-clean") or len(dirty)>330)
            owner=receipt["owners"]["portable_atomic"]
            seen=b"/dev/null/ohm-untracked-relink-inputs:" in z.read(tag+"portable_atomic.d").splitlines()
            assert seen==owner["marker"]==(role=="P")
            portable.add((owner["rmeta"],owner["rlib"]))
            binaries[role][phase]=receipt["elf"]
            if phase in ("old","settled","independent-clean"):
                info=receipt["binary"]; exe=store/info["sha256"]
                assert exe.name==receipt["elf"] and exe.name in persisted and exe.stat().st_size==info["bytes"]
                assert probe(exe)==receipt["probes"]
            if phase in scored:
                hw=parse(tag+"hardware.json")
                assert hw["instructions"]==receipt["instructions"]>0 and hw["status"]==0 and hw["enabled"]==hw["running"]>0
                counts[role][phase]=hw["instructions"]
        assert len(set(v for k,v in binaries[role].items() if k!="old"))==1 and binaries[role]["old"]!=binaries[role]["settled"]
        typed=[];links=[];devino=set(); prefix=role+"-census/tasks/"
        for s in z.read(prefix+"epochs.tsv").decode().splitlines():
            if not s.startswith("I ") or not s.endswith(" exec"):continue
            seq=int(s.split()[1]); f=z.read(prefix+f"{seq:05}.nul").split(b"\0");p=f[3]
            if p==b"/home/runner/work/_temp/ohm-foreign-join/sdk/bin/rustc" and b"--crate-name" in f[4:-1]:
                typed.append(f[f.index(b"--crate-name")+1].decode());devino.add(tuple(f[1:3]))
            elif p.endswith(b"/sdk/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"):
                links.append(seq)
        declared=parse(role+"-census/result.json")
        assert sorted(typed)==declared["typed_execs"]==(parent_roster if role=="P" else ["ruff","ty_python_semantic"])
        assert len(devino)==1 and len(links)==declared["wild_execs"]==1
        rosters[role]=sorted(typed)
    assert len(portable)==1
    decoded=parse("decoded-binaries.json"); recovered={}
    for phase in ("old","settled"):
        identities=[binaries[r][phase] for r in "PC"]
        key=hashlib.sha256(json.dumps([identities,cohorts],sort_keys=True).encode()).hexdigest()
        cache=here/("dwarf-"+key+".json")
        if not cache.exists():
            with tempfile.TemporaryDirectory(dir=here) as tmp:
                tmp=Path(tmp)
                for r,key0 in zip("PC",identities): os.link(store/key0,tmp/(r+"-"+phase))
                result=verify.section_parity(tmp,{"roles":cohorts},phase)
                assert result["entire_remainder_identical"] and result["string_inventory_differences"]==[0,0]
                for what,minimum in [("debug-info",1_000_000),("debug-macro",10_000)]:
                    v=verify.dump(tmp,{"roles":cohorts},phase,what)
                    assert v["different_lines"]==0 and v["lines"]>minimum
                    result[what]=v
                write(cache,result)
        recovered[phase]=json.loads(cache.read_bytes())
        assert recovered[phase]==decoded[phase]
    admitted=parse("accepted-pair.json"); cross={k:[counts[r][k]for r in "PC"]for k in scored}
    assert admitted=={"pair":pair,"counts":cross,"typed":rosters,"wild":{"P":1,"C":1}}
    assert all(2*c<=p for k,(p,c) in cross.items() if k!="edit")
    return {"boot":boot,"artifact":a["id"],"sha256":a["digest"],"bytes":a["size_in_bytes"],"counts":cross,
            "typed":rosters,"wild":{"P":1,"C":1},"binaries":{r:{k:v[k]for k in ("old","settled")}for r,v in binaries.items()},
            "decoded":decoded,"physical_inputs":len(persisted),"warnings":sum(common_diag.values()),"unit_count":350}
if __name__ == "__main__":
    for path in sorted(here.glob("*.github.json")):
        a=json.loads(path.read_bytes()); raw=here/(str(a["id"])+".zip");pair=a["pair_seen"]
        assert "sha256:"+digest(raw)==a["digest"] and raw.stat().st_size==a["size_in_bytes"]
        result=here/(pair+".reopened.json")
        with zipfile.ZipFile(raw)as z:
            assert z.testzip() is None and len(set(z.namelist()))==len(z.namelist())
            if pair=="8":
                assert "boot.json" not in z.namelist() and not any(n.endswith("hardware.json")for n in z.namelist())
                print("unregistered numeric job stopped before a family or price",flush=True);continue
            if not result.exists():
                write(result,archive(a,z));print("all independent gates passed for",pair,flush=True)
