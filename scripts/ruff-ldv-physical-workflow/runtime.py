"""Select source-built compiler directories at one stable rustup pathname; no wrapper or LLVM actor."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import transport
sys.path.insert(0,str(HERE.parent/"ruff-ldv-needed"))
import needed
import probes
import support
from support import census,guards,need,put,sha

DENY={"LD_PRELOAD","LD_AUDIT","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER","CARGO_BUILD_RUSTC_WRAPPER",
      "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER","OHM_LDV_GUARD"}


def clean(env):
    need(not any(k.startswith("QA_LDV_") or (k.startswith("CARGO_") and "TRUST" in k)
                 or k in DENY or (k in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS") and v) for k,v in env.items()),
         "unregistered compiler/plugin/wrapper environment")


def stat_id(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]


class Runtime:
    def __init__(self, work, inputs, out, tools):
        self.inputs,self.evidence,self.tools=inputs,out,tools
        self.manifests=transport.capsule.admit(inputs/"capsule")
        self.proof=json.loads((inputs/"source-qualification.json").read_bytes())
        self.sdk=work/"rustup/toolchains/ohm"
        self.sdk.parent.mkdir(parents=True)
        self.parked={k:inputs/"parked"/v for k,v in (("P","normal"),("C","defer"))}
        self.active=None
        self.refs={}
        for role, parked in self.parked.items():
            names=self.manifests[role]
            drv,=[n for n in names if n.startswith("lib/librustc_driver-")]
            llvm=transport.llvm_name(parked,names)
            chosen={"front":"bin/rustc","driver":drv,"llvm":llvm,"cargo":"bin/cargo","wild":support.WILD}
            data={key:{"name":n,"sha":names[n][0],"id":stat_id(parked/n)} for key,n in chosen.items()}
            need(all(sha(parked/r["name"])==r["sha"] for r in data.values()) and
                 data["driver"]["sha"]==self.proof["physical"][role]["driver"] and
                 data["wild"]["sha"]==transport.capsule.REG["signed_cargo"]["members"][support.WILD][3],"invalid physical role")
            self.refs[role]=data
        self.select("P")
        self.base={"HOME":str(work/"home"),"PATH":str(Path(shutil.which("rustup")).absolute().parent)+":/usr/bin:/bin",
                   "RUSTUP_HOME":str(work/"rustup"),"RUSTUP_AUTO_INSTALL":"0","CARGO_HOME":str(work/"unshared-cargo"),
                   "LD_LIBRARY_PATH":str(self.sdk/"lib"),"LC_ALL":"C","TZ":"UTC"}
        (work/"home").mkdir()
        versions={}
        for role in ("P","C"):
            self.select(role)
            versions[role]={}
            for which in ("rustc","cargo"):
                lookup=Path(subprocess.check_output(["rustup","which","--toolchain","ohm",which],env=self.base,text=True).strip())
                need(lookup.samefile(self.sdk/"bin"/which),"rustup selected a different installed tool")
                versions[role][which]=subprocess.check_output([which,"+ohm","-vV"],env=self.base,text=True)
        need(versions["P"]==versions["C"],"source compilers do not share the registered version output")
        self.select("P")
        put(out/"physical-roles.json",{"kits":self.refs,"versions":versions,"sdk":str(self.sdk),
                                       "source_qualification":sha(inputs/"source-qualification.json")})

    def select(self, role):
        need(role in self.parked,"unknown physical role")
        if self.active!=role:
            if self.active:
                need(not self.parked[self.active].exists(),"previous parked directory was replaced")
                self.sdk.rename(self.parked[self.active])
            need(self.parked[role].is_dir() and not self.parked[role].is_symlink() and not self.sdk.exists(),"unavailable SDK")
            self.parked[role].rename(self.sdk)
            self.active=role
        for n,r in self.refs[role].items():
            p=self.sdk/r["name"]
            need(stat_id(p)==r["id"] and p.samefile(self.inputs/"capsule/objects"/r["sha"]),"changed enrolled SDK identity")
            setattr(self,n,p)

    def env(self, base, arm, _where):
        need(arm=="plain","instrumented arm in physical study")
        clean(base)
        return base.copy()

    def finish(self):
        self.sdk.rename(self.parked[self.active])
        self.active=None
        for role,root in self.parked.items():
            for n,item in self.manifests[role].items():
                p=root/n
                need(p.samefile(self.inputs/"capsule/objects"/item[0]) and sha(p)==item[0],"source-built SDK changed")
        transport.capsule.admit(self.inputs/"capsule")


def real_opens(trace,rust,kit):
    rows={}
    began=False
    for line in trace.open():
        line=line.rstrip("\n")
        if line.startswith("execve(") and line.endswith("= 0"):
            m=support.EXEC.fullmatch(line)
            if m and ast.literal_eval(m[1])==rust["exec"]:
                began=True
        if not began or "O_RDONLY" not in line:
            continue
        m=re.search(r"= ([0-9]+)<(/[^>]*)>$",line)
        if not m:
            continue
        opened=Path(m[2])
        for key in ("driver","llvm"):
            r=kit.refs[kit.active][key]
            # Avoid stat'ing unrelated or ephemeral inputs from completed jobs.
            if not (opened.name.startswith("librustc_driver-") if key=="driver" else opened.name.startswith("libLLVM")):
                continue
            expected=kit.sdk/r["name"]
            need(opened.samefile(expected) and stat_id(opened)==r["id"] and sha(opened)==r["sha"],"wrong real rustc DSO")
            rows.setdefault(key,[]).append({"fd":int(m[1]),"path":str(opened),"sha":r["sha"],
                                           "dev_ino":r["id"][:2],"raw_sha":hashlib.sha256(line.encode()).hexdigest()})
    need(set(rows)=={"driver","llvm"},"the two actual compiler libraries were not both opened after real exec")
    return rows


def visit(kit,dest,work,repo,env,cmd,wanted,*,score,cold,observe):
    dest.mkdir()
    (dest/"native").mkdir()
    (dest/"trace").mkdir()
    clean(env)
    native=list(cmd)
    if score:
        native=needed.counted_argv(kit.tools/"count",dest/"pmu.json",shutil.which("cargo",path=env["PATH"]),native)
    flags=needed.STDIN_FLAGS if cold else ["-e","trace=%process"]
    if observe:
        need(not score and not cold,"off-clock opens must stay out of physical counters")
        flags=["-y","-e","trace=%process,openat,openat2"]
    argv=["/usr/bin/strace","-ff","-qq","-s","131072","-v",*flags,"-o",str(dest/"trace/exec"),"--",*native]
    put(dest/"command.json",{"ordinary":cmd,"actual":argv,"environment":env})
    code=guards.run(argv,repo,env,dest,work,dest,timeout=3000)
    need(code==wanted,("wrong ordinary Cargo verdict",str(dest),code,(dest/"outer.stderr").read_bytes()[-1200:]))
    pmsha=None
    if score:
        pm=json.loads((dest/"pmu.json").read_bytes())
        need(os.waitstatus_to_exitcode(pm["status"])==code and pm["enabled"]==pm["running"]>0 and pm["instructions"]>0,
             "incomplete inherited hardware counter")
        pmsha=sha(dest/"pmu.json")
    rusts,actual=support.observed(dest,kit.sdk,"plain",False)
    tree=json.loads((dest/"kernel.json").read_bytes())["tree"]
    linkids={(r["pid"],r["path"]) for r in tree["linkers"]}
    links=[]
    loads={}
    for trace in sorted((dest/"trace").glob("exec.*")):
        pid=int(trace.suffix[1:])
        with trace.open() as opened:
            for line in opened:
                if not line.startswith(("execve(","execveat(")) or not line.rstrip().endswith("= 0"):
                    continue
                m=support.EXEC.fullmatch(line.rstrip())
                need(m,("unparsed successful exec",line[:180]))
                exe,args,raw=(ast.literal_eval(s) for s in m.groups())
                environ=dict(p.split("=",1) for p in raw)
                clean(environ)
                if (pid,exe) in linkids:
                    links.append({"pid":pid,"path":exe,"argv":args,"sha256":sha(Path(exe)),
                                  "signed_wild":support.real_program(exe,kit.wild)})
    need(sorted((p["pid"],p["path"]) for p in links)==sorted(linkids),"unaccounted link exec")
    if observe:
        for r in rusts:
            if r["kind"]=="full":
                loads[r["pid"]]=real_opens(dest/"trace"/f"exec.{r['pid']}",r,kit)
    put(dest/"actual-libraries.json",loads)
    put(dest/"linker-argv.json",links)
    roster,originals=probes.capture(dest,rusts,tree,actual,cold)
    for row in originals:
        owner=row["equivalence"]
        store=kit.evidence/"probe-owners"
        store.mkdir(exist_ok=True)
        got=support.physical.keep(Path(owner["owner"]).resolve(strict=True),store,b"\x7fELF")
        need(got["sha256"]==owner["owner_sha256"],"different kernel probe owner")
    put(dest/"probes.json",originals)
    return rusts,actual,roster,originals,pmsha,loads
