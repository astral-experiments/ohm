#!/usr/bin/env python3
"""Unscored normal musl Cargo consumer, marker-compatibility and provider guard."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import APP, PRODUCER, TARGET, HARD, V2, LIB, blob, dep_records, fid, observe, save, sha
from subjects import Subjects
from fixture import Fixture

def require(test,*reasons):
    if not test:raise AssertionError(reasons)

def temporary_empty(roots,park):
    @contextlib.contextmanager
    def scope():
        park.mkdir()
        for root in roots:
            require(root.is_dir() and not root.is_symlink(),root)
            root.rename(park/root.name)
        try:
            yield
        finally:
            # Independent reference trees are agency-created; never discard an original.
            for root in roots:
                if root.exists():
                    require(root.is_dir() and not root.is_symlink(),root)
                    (park/"reference").mkdir(exist_ok=True)
                    root.rename(park/"reference"/root.name)
                (park/root.name).rename(root)
    return scope()

def native_elf(p,env,want,out,cas):
    raw=p.read_bytes()
    require(raw[:6]==b"\x7fELF\x02\x01" and int.from_bytes(raw[18:20],"little")==62,p)
    ph=subprocess.check_output(["readelf","-lW",p],env=env)
    dyn=subprocess.check_output(["readelf","-dW",p],env=env)
    require(b"INTERP" not in ph and b"(NEEDED)" not in dyn)
    proc=subprocess.run([p],env=env,capture_output=True,timeout=15)
    require(proc.returncode==want and not proc.stdout and not proc.stderr,(proc.returncode,want))
    h=hashlib.sha256(raw).hexdigest();f=cas/(h+".elf.gz")
    if not f.exists():blob(f,raw)
    blob(out/"elf-programs.gz",ph);blob(out/"elf-dynamic.gz",dyn)
    return h

class Trial:
    def __init__(self, subjects, work, out, layout, flavor):
        self.s=subjects; self.work=work;self.out=out;self.flavor=flavor;out.mkdir();work.mkdir()
        self.roots=[work/name for name in ("target","shared")]
        for p in self.roots:p.mkdir()
        self.env=self.s.env | {"CARGO_TARGET_DIR":str(self.roots[0]),"CARGO_BUILD_BUILD_DIR":str(self.roots[1])}
        self.fix=Fixture(work,self.env,flavor)
        self.cli=["cargo","+ohm"]
        if layout=="shared":self.cli+=["-Zohm-shared-registry-cache"]
        self.cli+=["build","--locked","--offline","--target",TARGET,"-p",APP,"--bin",APP,"--message-format=json"]
        subprocess.run(["cargo","+ohm","generate-lockfile","--offline"],env=self.env,cwd=self.fix.project,check=True,capture_output=True)
        self.fix.files.append(self.fix.project/"Cargo.lock");self.fix.original=self.fix.sources()
        self.out.joinpath("cas").mkdir()
        save(out/"fixture.json",{"files":self.fix.original,"body":{str(p.relative_to(self.fix.project)):p.read_text() for p in self.fix.files},
                                 "native_paths":[str(x) for x in self.fix.paths],"cli":self.cli})
        self.summaries=[];self.first_reads=[]
    def visit(self,label,want, *, producer, native="link", marker=None, translated=None, pretranslated=False, retained_v2=False):
        folder=self.out/label;folder.mkdir()
        roots=self.roots;fix=self.fix;env=self.env;cas=self.out/"cas";sdk=self.s.sdk
        require(fix.sources()==fix.original,label,"source or manifest changed")
        pre=dep_records(roots,cas)
        native_state=fix.state()
        with tempfile.TemporaryDirectory(dir=self.work,prefix="trace-") as t:
            traces=Path(t)
            cmd=["strace","-ff","--seccomp-bpf","-q","-ttt","-yy","-s","131072","-e",
                 "trace=execve,execveat,clone,clone3,fork,vfork,open,openat,openat2,rename,renameat,renameat2,unlink,unlinkat",
                 "-o",str(traces/"pid"),*self.cli]
            p=subprocess.run(cmd,cwd=fix.project,env=env,capture_output=True,timeout=150)
            blob(folder/"cargo.stdout.gz",p.stdout);blob(folder/"cargo.stderr.gz",p.stderr)
            require(not any(line.startswith(b"strace:") and b"seccomp" in line.lower() for line in p.stderr.splitlines()),label,"kernel syscall filter unavailable",p.stderr[-600:])
            with tarfile.open(folder/"syscalls.tgz","x:gz",compresslevel=2) as archive:
                for raw in sorted(traces.iterdir()):archive.add(raw,arcname=raw.name,recursive=False)
            data=observe(traces,fix.project,sdk,roots,{str(x) for x in fix.paths})
        save(folder/"kernel.json",data)
        post=dep_records(roots,cas)
        save(folder/"dep-files.json",{"before":pre,"after":post,"opened":data["dep_read"],"writes":data["dep_writes"]})
        require(fix.sources()==fix.original and fix.state()==native_state,label,"inputs changed during actual Cargo")
        code=0 if want is not None else 101
        require(p.returncode==code==data["status"],label,p.returncode,code,p.stderr[-700:])
        typed=[json.loads(l) for l in p.stdout.splitlines()]
        require(typed[-1]=={"reason":"build-finished","success":code==0},label)
        build=[m for m in typed if m["reason"]=="build-script-executed"]
        require(len(build)==1 and build[0]["linked_paths"]==["native="+str(p.parent) for p in fix.paths],label,build)
        expected_output=b"cargo:rerun-if-changed=build.rs\n"+b"".join(("cargo:rustc-link-search=native="+str(path.parent)+"\n").encode() for path in fix.paths)
        unit_root=Path(build[0]["out_dir"]).parent
        require(any(unit_root.is_relative_to(root) for root in roots),label,unit_root)
        outputs=[path for path in (unit_root/"run/stdout",unit_root/"output") if path.is_file()]
        require(len(outputs)==1,label,"missing active build.rs stdout",outputs)
        output=outputs[0].read_bytes();blob(folder/"build-script-stdout.gz",output)
        require(output==expected_output,label,"build.rs must watch only build.rs",outputs,output)
        for c in [r for r in post if r["role"]==APP and r["kind"]=="raw"]:
            require(c["parsed"]==[],label,"consumer has its own marker",c)
        if code==0:require(any(r["role"]==APP and r["kind"]=="raw" for r in post),label)
        c=data["cargo"];require(c["argv"][1:]==self.cli[2:] and c["identity"]==fid(sdk/"bin/cargo"),c,self.cli)
        compilers=data["compilers"];pc=[c for c in compilers if c["crate"]==PRODUCER]
        bc=[c for c in compilers if c["crate"]==APP]
        unrecognized={c["crate"] for c in compilers}-{PRODUCER,APP,"build_script_build"}
        require(not unrecognized,label,unrecognized)
        for c in compilers:
            require(any(pid==c["pid"] and Path(path).samefile(sdk/"lib"/self.s.driver) for pid,path,_ in data["driver_open"]),label,c)
        artifact=[m for m in typed if m["reason"]=="compiler-artifact" and m["target"]["name"]==PRODUCER]
        if producer=="fresh":
            require(len(artifact)==1 and artifact[0]["fresh"] and not pc and not data["scripts"],label,artifact,pc,data["scripts"])
        elif producer=="full":
            require(any(c["kind"]=="full" and c["argv"][c["argv"].index("--target")+1]==TARGET and
                        "-Zohm-check-relink-inputs" in c["argv"] for c in pc),label,pc)
        elif producer=="switch":
            require(not artifact or len(artifact)==1,label)
        else:raise ValueError(producer)
        # A compiler switch can keep multiple namespaces with the exact same unit hash.
        # Resolve the actual producer from Cargo's artifact and the native compiler arguments.
        directories={Path(path).parent for row in artifact for path in row["filenames"] if path.endswith(".rlib")}
        directories.update(Path(c["argv"][c["argv"].index("--out-dir")+1]) for c in pc)
        for c in bc:
            for i,v in enumerate(c["argv"][:-1]):
                spec=c["argv"][i+1]
                if v=="--extern" and spec.startswith(PRODUCER+"="):
                    directories.add(Path(spec.split("=",1)[1]).parent)
        require(len(directories)==1,label,"ambiguous live producer",directories)
        outdir,=directories;require(outdir.name=="out" and any(outdir.is_relative_to(r) for r in roots),label,outdir)
        finger=outdir.parent/"fingerprint"/("dep-lib-"+PRODUCER)
        candidates=[r for r in post if r["role"]==PRODUCER]
        chosen=[r for r in candidates if Path(r["path"])==finger or r["kind"]=="raw" and Path(r["path"]).parent==outdir]
        kept_child_receipt=retained_v2 and not pc
        if kept_child_receipt:
            require(producer=="switch" and self.s.active==("P","aware"),label)
            require(any(r["kind"]=="encoded" and r["role"]==PRODUCER and r["parsed"]["LNK1"]==V2 and
                        any(c["path"]==r["path"] and c["identity"]==r["identity"] and c["raw_sha256"]==r["raw_sha256"] for c in chosen)
                        for r in pre), label, "fresh same-stamp parent must reuse the exact old child evidence")
            marker,translated=[V2],V2
        if marker is not None:
            raw=[r for r in chosen if r["kind"]=="raw"]
            if native!="bundled-error" or raw:
                require(raw and all(r["parsed"]==marker for r in raw),label,raw,marker)
        if translated is not None:
            enc=[r for r in chosen if r["kind"]=="encoded"]
            require(enc and all(r["parsed"]["markers"]==marker and r["parsed"]["LNK1"]==translated for r in enc),label,enc,translated)
        elif marker is not None and code==0:
            enc=[r for r in chosen if r["kind"]=="encoded"]
            require(enc and all(r["parsed"]["markers"]==marker and not r["parsed"]["LNK1"] for r in enc),label,enc)
        if native in ("bundled","bundled-error"):
            selected=str(fix.paths[0] if fix.paths[0].exists() else fix.paths[1])
            require({p for c in pc for p in c["provider_opens"]}=={selected},label,pc)
        else:
            require(not any(c["provider_opens"] for c in pc),label,"unbundled provider opened by producer",pc)
        if native=="noop":
            require(not compilers and not data["scripts"] and not data["linkers"],label,data["linkers"],compilers)
        elif native=="bundled-error":
            require(not bc and not data["linkers"],label,bc,data["linkers"])
        else:
            require(len(bc)==1 and bc[0]["argv"][bc[0]["argv"].index("--target")+1]==TARGET and len(data["linkers"])==1,label,bc,data["linkers"])
            ld=data["linkers"][0]
            require(ld["exit"]==0 if code==0 else ld["exit"] not in (0,None),label,ld)
            if native=="link":
                selected=str(fix.paths[0] if fix.paths[0].exists() else fix.paths[1])
                require(data["selected"]==[selected],label,selected,data["selected"])
                if selected==str(fix.paths[1]):
                    before=[t for t,_,how,n in ld["lookup_order"] if how=="absent" and n==str(fix.paths[0])]
                    after=[t for t,_,how,n in ld["lookup_order"] if how=="opened" and n==selected]
                    require(before and after and min(before)<=min(after),label,ld)
            elif native=="bundled":
                require(not data["selected"],label,data["selected"])
            else:raise ValueError(native)
        exe=None
        if code==0:
            binaries=[Path(m["executable"]) for m in typed if m["reason"]=="compiler-artifact" and m.get("executable") and m["target"]["name"]==APP]
            require(len(binaries)==1,label,binaries)
            exe=native_elf(binaries[0],env,want,folder,cas)
        else:
            msg="\n".join(m["message"]["rendered"] or m["message"]["message"] for m in typed
                          if m["reason"]=="compiler-message" and m["message"]["level"]=="error")
            require("ohm_musl_v2_choice" in msg,label,msg)
        overlap=[]
        for before in pre:
            if before["kind"]!="encoded" or before["role"]!=PRODUCER:continue
            for when,pid,path in data["dep_read"]:
                if path!=before["path"]:continue
                # Before the first observed writer the raw bytes are still the immutable pre-visit body.
                if any(t<=when and (name==path or name is None and before["path"] in line)
                       for t,_,name,line in data["dep_writes"]):continue
                overlap.append([path,before["identity"],before["raw_sha256"],before["parsed"]["LNK1"],when])
        if kept_child_receipt:require(any(read[3]==V2 for read in overlap),label,"fresh same-stamp parent did not read the old child receipt")
        report={"producer_outdir":str(outdir),"producer_dep_record":str(finger),"retained_child_receipt_on_parent":kept_child_receipt,"label":label,"roles":self.s.active,"verdict":want,"cargo":code,"elf":exe,"producer":[c["kind"] for c in pc],
                "consumer":[c["kind"] for c in bc],"build_scripts":len(data["scripts"]),"native":data["selected"],
                "native_files":native_state,"ld":[[e["image"],e["sha256"],e["exit"]] for e in data["linkers"]],
                "translated_preexisting_reads":overlap,"roots":{str(r):fid(r)[:2] for r in roots},
                "raw_trace":sha(folder/"syscalls.tgz"),"kernel":sha(folder/"kernel.json")}
        save(folder/"result.json",report);self.summaries.append(report)
        if pretranslated:
            active_encoded={r["path"] for r in chosen if r["kind"]=="encoded"}
            self.first_reads.append({"label":label,"active_encoded":sorted(active_encoded),
                "observed_prior_v2":any(row[3]==V2 and row[0] in active_encoded for row in overlap),"read":overlap})
        return report
    def pair(self,label,want,producer,marker, *, skip=False,bundled=False,pretranslated=False,retained_v2=False):
        mark=[] if marker is None else [marker]
        trailer=V2 if mark==[V2] and self.s.active[1]=="aware" else None
        native="noop" if skip else ("bundled-error" if want is None else "bundled") if bundled else "link"
        warm=self.visit(label+"-warm",want,producer=producer,native=native,marker=mark,
                        translated=trailer,pretranslated=pretranslated,retained_v2=retained_v2)
        with temporary_empty(self.roots,self.work/("park-"+label)):
            require(all(not p.exists() for p in self.roots),self.roots)
            for p in self.roots:p.mkdir()
            clean=self.visit(label+"-empty",want,producer="full",native=native if not skip else "link",
                             marker=mark,translated=trailer)
        require((warm["elf"],warm["cargo"],warm["verdict"])==(clean["elf"],clean["cargo"],clean["verdict"]),label,warm,clean)
        if not skip:require(warm["native"]==clean["native"],label)
        # Only discard this invocation's known independent empty target after all evidence is retained.
        ref=self.work/("park-"+label)/"reference"
        require(ref.parent.parent==self.work and set(p.name for p in ref.iterdir())=={"target","shared"} and not ref.is_symlink(),ref)
        shutil.rmtree(ref)
    def finish(self):
        save(self.out/"terminal.json",{"phases":self.summaries,"pretranslated":self.first_reads})

def mechanism(s,work,out,layout):
    def fresh(name,flavor,driver):
        s.select(driver,"aware")
        return Trial(s,work/name,out/name,layout,flavor)
    c=fresh("candidate-v2","comment","C")
    c.pair("cold-low",17,"full",V2)
    for label,state,verdict in [("settled",None,17),("insert",29,29),("same-inode",47,47),
                                ("bad","bad",None),("bad-repeat","bad",None),("repair",29,29),("remove",None,17)]:
        c.fix.mutate(state);c.pair(label,verdict,"fresh",V2)
    c.finish()
    p=fresh("parent-hard","comment","P")
    p.pair("cold",17,"full",HARD);p.pair("settled",17,"full",HARD)
    p.fix.mutate(29);p.pair("insert",29,"full",HARD);p.finish()
    control=fresh("marker-free-sham","plain","C")
    control.pair("cold",17,"full",None);control.pair("settled",17,"fresh",None,skip=True);control.finish()
    for flavor in ("bundled","unknown"):
        x=fresh("veto-"+flavor,flavor,"C");bundle=flavor=="bundled"
        x.pair("cold",17,"full",HARD,bundled=bundle)
        x.fix.mutate(29);x.pair("insert",29,"full",HARD,bundled=bundle)
        x.fix.mutate("bad");x.pair("malformed",None,"full",HARD,bundled=bundle)
        x.fix.mutate(47);x.pair("repair",47,"full",HARD,bundled=bundle);x.finish()

def migration(s,work,out,layout,old):
    s.select("C",old)
    trial=Trial(s,work/"transition",out/"transition",layout,"comment")
    # Same canonical roots, same C rustc, reversible Cargo switches. A raw-v2 old writer
    # and a v2-aware LNK1 writer are both trained and then used in both directions.
    trial.pair("old-cold-v2",17,"full",V2)
    trial.pair("old-raw-v2-repeat",17,"full",V2)
    trial.fix.mutate(29);trial.pair("old-raw-v2-new-provider",29,"full",V2)
    s.select("C","aware")
    trial.fix.mutate(47);trial.pair("new-reader-of-old",47,"switch",V2)
    trial.pair("new-reader-settled",47,"fresh",V2)
    s.select("C",old)
    trial.fix.mutate("bad");trial.pair("old-reader-of-LNK1",None,"full",V2,pretranslated=True)
    trial.fix.mutate(29);trial.pair("old-reader-repair",29,"full",V2)
    s.select("C","aware")
    trial.fix.mutate(None);trial.pair("new-reader-restore",17,"switch",V2)
    trial.pair("new-reader-repeat",17,"fresh",V2)
    # The same rustc -vV and physical launcher stay installed while only the driver
    # changes. An old conservative marker must recover; return to C and observe v2.
    s.select("P","aware")
    trial.fix.mutate(29);trial.pair("parent-driver",29,"switch",HARD,retained_v2=True)
    trial.pair("parent-driver-repeat",29,"switch",HARD,retained_v2=True)
    s.select("C","aware")
    trial.fix.mutate("bad");trial.pair("child-driver-malformed",None,"switch",V2)
    trial.fix.mutate(47);trial.pair("child-driver-repair",47,"fresh",V2)
    trial.finish()
    require(len(trial.first_reads)==1 and trial.first_reads[0]["observed_prior_v2"],
            "the ordinary old Cargo did not observably open an unchanged v2-encoded record; namespace isolation is a separate, insufficient result",trial.first_reads)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subjects",type=Path,required=True)
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--layout",choices=("private","shared"),default="private")
    parser.add_argument("--suite",choices=("mechanism","migration"),required=True)
    parser.add_argument("--legacy",choices=("signed","strict"))
    args=parser.parse_args()
    require(not sys.flags.optimize,"Python assertions must be enabled")
    require((args.suite=="migration")==bool(args.legacy),"supply --legacy only for migration")
    for tool in ("rustup","musl-gcc","ar","readelf","b3sum","strace"):
        require(shutil.which(tool),"missing required executable",tool)
    require(sha(Path(shutil.which("strace")))=="28f957c227012de0b18d1bd7fff2d396cb693ea60ed8013be68de071e84b5001","requires the audited Ubuntu 6.8-0ubuntu2 amd64 strace")
    work=args.work.resolve();out=args.out.resolve()
    require(work!=out and not work.is_relative_to(out) and not out.is_relative_to(work))
    require(not any(x in str(p) for x in (" ",":","\n","\t") for p in (work,out)), "unescaped proof paths required")
    for p in (work,out):
        require(not p.exists() and p.parent.exists(),"fresh, independent path required",p)
        p.mkdir(mode=0o700)
    specs=json.loads(args.subjects.read_bytes())
    save(out/"enrolled.json",{"inputs":specs,"subject_manifest":sha(args.subjects),"argv":sys.argv,"originals":{n:sha(Path(__file__).parent/n) for n in ("guard.py","evidence.py","fixture.py","subjects.py")}})
    try:
        subjects=Subjects(specs,work,out,["aware"]+([args.legacy] if args.legacy else []))
        if args.suite=="mechanism":mechanism(subjects,work,out,args.layout)
        else:migration(subjects,work,out,args.layout,args.legacy)
        save(out/"complete.json",{"suite":args.suite,"layout":args.layout,"legacy":args.legacy,
                                 "histories":{str(p.relative_to(out)):sha(p) for p in sorted(out.glob("*/terminal.json"))},
                                 "identities":sha(out/"subjects.json"),"selections":subjects.visits})
    except BaseException:
        import traceback
        save(out/"refused.json",{"traceback":traceback.format_exc(),"last_closed":[str(p.relative_to(out)) for p in sorted(out.glob("*/*/result.json"))]})
        raise
if __name__=="__main__":main()
