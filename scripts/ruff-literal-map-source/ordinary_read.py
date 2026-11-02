"""Reassemble all original rlibs and rerun the typed clients before accepting the reuse screen."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import ordinary as run
import native_payload as n
from acquire import LOG,ROOT,json_save,sha

def load(path):return json.loads(path.read_bytes())

def reassemble(path,recipe,blob):
    with path.open("wb") as out:
        out.write(b"!<arch>\n")
        for text,key in recipe:
            head=bytes.fromhex(text);body=blob(key);size=int(head[48:58])
            n.need(len(head)==60 and head[58:]==b"`\n" and body.stat().st_size==size,"bad physical archive member")
            out.write(head)
            with body.open("rb") as f:shutil.copyfileobj(f,out,1<<20)
            if size%2:out.write(b"\n")

def main():
    enrollment=load(LOG/"qualified-inputs.json")
    n.need(enrollment["head"]==os.environ["GITHUB_SHA"] and enrollment["command"]==run.CMD and
           enrollment["sources"]==run.SOURCES and enrollment["factory"]==41431225435,"different ordinary invocation")
    data={};parsed={};bodies=set();layouts=set();compared={}
    with tempfile.TemporaryDirectory(dir=ROOT) as scratch:
        base=Path(scratch);working=base/"reassembled.rlib"
        def blob(key):
            n.need(len(key)==64 and all(c in "0123456789abcdef" for c in key),"invalid physical blob")
            dest=base/key
            if not dest.exists():
                run.guard()
                with dest.open("xb") as f:subprocess.run(["zstd","-dcq",LOG/"native-bodies"/(key+".zst")],stdout=f,check=True)
                n.need(sha(dest)==key,"changed preserved native payload")
            bodies.add(key);return dest
        for role in "SPC":
            for stage in (("empty",) if role=="S" else ("empty","history")):
                for rev in ("old","new"):
                    label=f"{stage}-{role}-{rev}";d=LOG/label;r=load(d/"visit.json")
                    rows=[json.loads(x) for x in gzip.decompress((d/"cargo.stdout.gz").read_bytes()).splitlines()]
                    n.need(rows[-1]=={"reason":"build-finished","success":True} and
                           not [i for i in rows if i.get("reason")=="compiler-message" and i["message"].get("level")=="error"],
                           "failed original Cargo verdict")
                    placement=run.normal_registry.capture(rows,run.STATE,False)
                    saved=load(d/"registry.json")
                    for entry in saved["files"]:n.need(min(entry.pop("identity"))>0,"invalid registry file identity")
                    n.need(saved==placement and {k:placement[k] for k in ("products","shared","sha256")}==r["registry"],
                           "different physical registry placement")
                    products=[x for x in rows if x["reason"]=="compiler-artifact"]
                    n.need(all(i["package_id"].rsplit("#",1)[1] in enrollment["locked_archives"] for i in products
                           if i["package_id"].startswith("registry+")),"product outside the registered lock")
                    roster=sorted([i["package_id"],i["target"]["name"],i["target"]["kind"],i["features"],i["profile"]["test"]] for i in products)
                    dirty=sorted(i["target"]["name"] for i in products if not i["fresh"])
                    n.need(len(products)==r["units"] and dirty==r["dirty"] and run.norm(roster)==r["roster"] and
                           (r["role"],r["source"],r["revision"])==(role,rev,run.SOURCES[rev]),"different unit roster or source")
                    refs=load(d/"native-archives.json");ledger=load(d/"incremental-objects.json")
                    for owner in run.OWNERS:
                        key=refs[owner]["sha256"];layouts.add(key)
                        if key not in parsed:
                            reassemble(working,load(LOG/"archive-layouts"/(key+".json")),blob)
                            n.need(sha(working)==key and working.stat().st_size==refs[owner]["size"],"different complete original rlib")
                            parsed[key]=n.manifest(working)
                        n.need(parsed[key]==refs[owner]["payload"],"native archive record is not its real bytes")
                        complete=n.stable(parsed[key]);physical={}
                        for name,row in ledger[owner]["objects"].items():
                            a,b=row["before"],row["after"]
                            kept=bool(a and b and a[:2]==b[:2])
                            n.need(kept is row["retained"] and (not kept or a[2]==b[2] and
                                   row["before_sha256"]==row["after_sha256"]),"unqualified old inode")
                            if b:physical[name]=[row["after_sha256"],b[2]]
                        n.need(physical==complete,"packaged native bytes differ from the full incremental object set")
                    executable=blob(r["client"]["sha256"]);n.need(executable.stat().st_size==r["client"]["size"],"different client ELF");executable.chmod(0o700)
                    for name,(text,old,new) in run.scout.CASES.items():
                        expect=("F401=1 used=0 invalid=1\n"+(old if rev=="old" else new)).encode()
                        child=subprocess.run([executable,text],cwd=base,env=dict(PATH="/usr/bin:/bin",LC_ALL="C",LD_LIBRARY_PATH=str(run.ROLES[role]/"lib")),
                                             capture_output=True,timeout=40)
                        n.need(child.returncode==0 and not child.stderr and
                               child.stdout==expect==r["verdicts"][name].encode()==gzip.decompress((d/(name+".stdout.gz")).read_bytes()),
                               "different executed typed linter or Unicode verdict")
                    data[stage,role,rev]=dict(record=r,archives=refs,ledgers=ledger)
        n.need({p.name for p in (LOG/"native-bodies").iterdir()}=={k+".zst" for k in bodies} and
               {p.name for p in (LOG/"archive-layouts").iterdir()}=={k+".json" for k in layouts},"unregistered native material")
    first=data["empty","S","old"]["record"]
    for obj in data.values():
        r=obj["record"];n.need((r["registry"],r["roster"],r["units"])==(first["registry"],first["roster"],first["units"]),
                              "different signed placement")
    changed={}
    for role in "SPC":
        x,y=[data["empty",role,rev]["archives"]["ruff_python_literal"]["payload"] for rev in ("old","new")]
        changed[role]=n.compare_objects(x,y);n.need(any(changed[role].values()),"actual leaf native code did not change")
    for rev in ("old","new"):
        for role in "PC":
            for owner in run.OWNERS:
                ref=data["empty",role,rev]["archives"][owner]["payload"]
                got=data["history",role,rev]["archives"][owner]["payload"]
                compared[f"history-{role}-{rev}-vs-empty-{owner}"]=n.compare_objects(ref,got)
        for owner in run.OWNERS:
            x,y=[data["empty",role,rev]["archives"][owner]["payload"] for role in "PC"]
            compared[f"empty-P-vs-C-{rev}-{owner}"]=n.compare_objects(x,y)
    n.need(compared==load(LOG/"clean-comparisons.json") and not any(v for row in compared.values() for v in row.values()),
           "different complete native products for equal source")
    result=run.opportunity(data["history","P","new"],data["history","C","new"])
    accepted=load(LOG/"accepted.json")
    n.need(all(accepted[k]==v for k,v in result.items()),"different source reuse opportunity")
    json_save(LOG/"reopened.json",dict(**accepted,physical_archives=len(layouts),unique_native_blobs=len(bodies),
              native_source_changes=changed,typed_executions=5*len(data),independent_clean_comparisons=len(compared),
              physical_bytes=sum(f.stat().st_size for f in (LOG/"native-bodies").iterdir())))
    print(json.dumps(result))

if __name__=="__main__":main()
