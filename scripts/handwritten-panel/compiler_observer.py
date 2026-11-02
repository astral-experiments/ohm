"""Corroborate native Cargo's full compiler argv with successful kernel exec events."""
from pathlib import Path
import copy
import os
import re
import subprocess
import sys
import material as m
import exec_events as k

CAP=m.HERE/"exec_events.py"; FIX=m.HERE/"exec_fixture.py"
def capture(path,argv,env,cwd,compiler,role,runtime):
    path.mkdir()
    launch={"command":argv,"environment":env,"cwd":str(cwd),"role":role,"runtime":runtime,"score":False,
            "cargo_file":k.file_id(Path(argv[0])),"compiler_file":k.file_id(compiler),"kernel_reader_sha256":m.filesha(CAP)}
    m.save(path/"launch.json",launch)
    subprocess.run([sys.executable,"-ISB",str(CAP),str(path/"launch.json")],env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},timeout=1500,check=True)
def inputs(path):
    p=next(p for p in path.parents if(p/"intake.json").is_file()and(p/"intake/role-material").is_dir())
    role,=[r for r in m.P["roles"] if path.parent.name.endswith("-"+r)]
    data=m.read(p/"intake.json")["installed"][role]
    m.guard(data["source"]==m.P["roles"][role] and data["runtime"]["bin/cargo"]==m.P["signed_cargo_sha256"],"selected native SDK")
    return role,data["runtime"]
def kernel_result(path):
    f=path/"kernel-events.json";m.guard(f.is_file()and 0<f.stat().st_size<=16<<20,"kernel journal budget")
    v=k.decode(m.read(f));r=m.read(path/"launch.json");root=v["images"][0]
    m.guard(r["score"] is False and r["kernel_reader_sha256"]==m.filesha(CAP) and v["exits"][v["root"]]==0 and
            root["argv"]==r["command"] and root["file"]==r["cargo_file"],"wrong completed root exec")
    return v,r
def messages(raw):
    lines=raw.splitlines()
    assert lines and re.fullmatch(rb"    Finished `dev` profile \[unoptimized \+ debuginfo\] target\(s\) in [0-9.hms ]+",lines[-1])
    return sorted(lines[:-1])
def verify(path,argv,expected):
    tree,launch=kernel_result(path);role,runtime=inputs(path);selected=[]
    m.guard(launch["command"]==argv and launch["environment"]==m.ENV and launch["cwd"]==str(m.SRC) and
            launch["role"]==role and launch["runtime"]==runtime and tree["images"][0]["exe"]==argv[0],"wrong SDK, native command, or environment")
    for e in tree["images"]:
        a=e.get("argv",[])
        if e["file"]==launch["compiler_file"]or Path(e["exe"]).name=="rustc"or(a and Path(a[0]).name=="rustc"):
            m.guard(a and a[0]==e["exe"]==str(m.RUSTC) and e["file"]==launch["compiler_file"] and tree["exits"].get(e["pid"])==0,"compiler image, arg0, or exit")
            selected.append({"pid":e["pid"],"argv":a})
    m.guard(len({e["pid"]for e in selected})==len(selected) and sorted(e["argv"]for e in selected)==sorted(expected),"genuine rustc count/full argv mismatch")
    m.guard(path.name in ("preclock-exec","scoped"),"unknown exec observation")
    ordinary=path.parent/("A-to-B"if path.name=="preclock-exec"else"native")
    m.guard(not (path/"stdout").read_bytes() and not(ordinary/"cargo.stdout").read_bytes() and
            messages((path/"stderr").read_bytes())==messages((ordinary/"cargo.stderr").read_bytes()),"direct/observed nonverbose Cargo output, excluding only elapsed time and order")
    return {"command":argv,"score":False,"compilations":selected,"all_rustc":len(selected),"kernel_execs":len(tree["images"]),
            "kernel_births":len(tree["births"]),"nonleader_handoffs":len(tree["handoffs"]),"kernel_sha256":m.filesha(path/"kernel-events.json")}
def fixture_events(a,al):
    true=[e for e in a["images"]if e["file"]==al["compiler_file"]]
    names=["shell","sibling","failed","nonleader",*[f"rapid-{i}"for i in range(4)]]
    m.guard(sorted(e["argv"] for e in true)==sorted([["/usr/bin/true",n]for n in names])and all(a["exits"][e["pid"]]==0 for e in true),"short, shell or failed exec corrupted")
    nonleader,=[e for e in true if e["argv"][-1]=="nonleader"]
    m.guard(a["handoffs"].get(nonleader["previous_tid"])==nonleader["pid"] and len(a["handoffs"])==1 and
            len({e["pid"]for e in true})==8 and all("/missing-closure-fixture"!=e["exe"] for e in a["images"])and
            any(Path(e["exe"]).name in ("dash","sh","bash") for e in a["images"]),"missing nonleader, failed exec or shell evidence")
    m.guard(len(a["images"])==10,"unexpected fixture image, absent shell, or extra exec")
    return true
def calibration(path):
    receipt=m.read(path/"inputs.json");signed=receipt["signed_cargo"]
    m.guard(receipt["cargo_sha256"]==m.P["signed_cargo_sha256"] and receipt["fixture_sha256"]==m.filesha(FIX),"calibration inputs")
    a,al=kernel_result(path/"fixture");b,bl=kernel_result(path/"signed-cargo")
    true=fixture_events(a,al)
    m.guard(bl["command"]==[signed,"-Vv"] and b["images"][0]["exe"]==signed and sum(e["file"]==bl["cargo_file"] for e in b["images"])==1 and not any(Path(e["exe"]).name=="rustc" for e in b["images"]) and
            (path/"signed-cargo/stdout").read_bytes()==(path/"direct-version.stdout").read_bytes() and not(path/"signed-cargo/stderr").read_bytes() and
            ("commit-hash: "+m.P["signed_cargo_commit"]+"\n")in(path/"direct-version.stdout").read_text(),"signed Cargo and direct version")
    return {"true_execs":len(true),"kernel_fixture_execs":len(a["images"]),"nonleader_handoffs":len(a["handoffs"]),"signed_cargo_execs":1,"signed_version_helper_execs":len(b["images"])-1}
class Observer:
    def __init__(self,argv,expected):self.argv=list(argv);self.expected=sorted(expected)
    def execute(self,path,argv,env,cwd):
        m.guard(argv==self.argv and env==m.ENV and cwd==m.SRC and path.is_absolute() and not path.exists(),"wrong scoped command")
        role,runtime=inputs(path)
        for n,h in runtime.items():m.guard(m.filesha(m.SDK/n)==h,"pre-observation compiler/Cargo/driver/LLVM")
        capture(path,argv,env,cwd,m.RUSTC,role,runtime)
        result=verify(path,self.argv,self.expected);m.save(path/"compiler-execs.json",result);return result
    def replay(self,path):
        if path.name=="trace-calibration":return calibration(path)
        result=verify(path,self.argv,self.expected);m.guard(result==m.read(path/"compiler-execs.json"),"unreproducible kernel exec journal");return result
    def calibrate(self,path,signed=None):
        if signed is None:
            w,tmp=m.host();options=[m.SDK/"bin/cargo",*(tmp/"ctfe22-root-sdks"/r/"bin/cargo"for r in m.P["roles"])]
            signed=next(f for f in options if f.is_file()and m.filesha(f)==m.P["signed_cargo_sha256"])
        signed=signed.resolve(strict=True);assert m.filesha(signed)==m.P["signed_cargo_sha256"]
        path.mkdir();env={"PATH":"/usr/bin:/bin","LC_ALL":"C"};cwd=path
        m.save(path/"inputs.json",{"signed_cargo":str(signed),"cargo_sha256":m.filesha(signed),"fixture_sha256":m.filesha(FIX)})
        cap=subprocess.run([str(signed),"-Vv"],cwd=cwd,env=env,check=True,capture_output=True);assert not cap.stderr
        (path/"direct-version.stdout").write_bytes(cap.stdout)
        capture(path/"fixture",[sys.executable,"-ISB",str(FIX)],env,cwd,Path("/usr/bin/true"),"fixture",{})
        capture(path/"signed-cargo",[str(signed),"-Vv"],env,cwd,signed,"genuine-signed-cargo",{})
        return calibration(path)
    def mutations(self,path):
        v=calibration(path);raw=m.read(path/"fixture/kernel-events.json");truth=k.decode(raw)
        fixture_launch=m.read(path/"fixture/launch.json")
        def check(x):
            fixture_events(k.decode(x),fixture_launch)
        exe=next(i for i,r in enumerate(raw["events"])if len(r)==4 and r[0]!=raw["root"]);ex=next(i for i,r in enumerate(raw["events"])if len(r)==2 and type(r[1])is int)
        birth=next(i for i,r in enumerate(raw["events"])if len(r)==3)
        change=next(i for i,r in enumerate(raw["events"])if len(r)==4 and r[0]!=r[2])
        wanted=[("missing successful exec",lambda x:x["events"].pop(exe)),("extra successful exec",lambda x:x["events"].append(x["events"][exe])),
                ("missing terminal TID",lambda x:x["events"].pop(ex)),("wrong kernel parent",lambda x:x["events"][birth].__setitem__(0,0)),
                ("hidden nonleader handoff",lambda x:x["events"][change].__setitem__(2,x["events"][change][0])),
                ("missing exec tracing",lambda x:x.__setitem__("options",0))]
        for label,alter in wanted:
            candidate=copy.deepcopy(raw);alter(candidate)
            try:check(candidate)
            except (AssertionError,KeyError,ValueError):continue
            raise AssertionError(label)
        return [v[0]for v in wanted]
