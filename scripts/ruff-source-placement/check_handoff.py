"""Off-counter metadata→codegen and failed-check→repaired-build on the real historical Ruff edit."""
import gzip
import json
import subprocess
import tomllib
from pathlib import Path

from common import need, save, sha
import durable
import storage
import tracking
from durable import acquire, guards, pilot, replay, runtime, study, support


def exercise(kit,root,source):
    suite=root/"workflow-option"; work=suite/"work";repo=suite/"ruff";donor=suite/"registry-donor"
    out=kit.evidence/"check-to-build";out.mkdir()
    env=kit.base|{"CARGO_HOME":str(work/"cargo-home"),"CARGO_TARGET_DIR":str(work/"target"),"CARGO_BUILD_BUILD_DIR":str(work/"build")}
    build=acquire.source_entry(source,"option")["command"];check=list(build);i=check.index("build");check[i]="check"
    gold=study.source_pair(source); refs=json.loads((kit.evidence/"option/acquired.json").read_bytes())
    deps={f"{r['name']}-{r['version']}.crate":r["checksum"] for r in tomllib.loads((source/"Cargo.lock").read_text())["package"] if "checksum" in r}
    terminal={}
    for role in ("P","C"):
        kit.select(role)
        case=out/role;case.mkdir()
        guards.admit(guards.resources(work,case),entry=True);study.write_source(repo,study.OLD,False)
        with replay.empty_roots(work,case):
            home=work/"cargo-home";(home/"registry").mkdir()
            for x in ("cache","index"):
                subprocess.run(["cp","-a","--reflink=auto",donor/"registry"/x,home/"registry"/x],check=True)
            subprocess.run(["cargo","+ohm","fetch","--locked","--offline"],env=env,cwd=repo,check=True)
            need(pilot.registry(home)==deps,"incorrect selected check registry")
            visits={}
            for phase,cmd,rev,bad in (("empty-check-old",check,study.OLD,False),("build-after-check-old",build,study.OLD,False),
                                    ("invalid-check-new",check,study.NEW,True),("build-after-repair-new",build,study.NEW,False),
                                    ("repeat-build-new",build,study.NEW,False)):
                want=101 if bad else 0;loc=case/phase
                before=study.write_source(repo,rev,bad)
                with tracking.add_file_calls(guards,loc):
                    rusts,counts,_,_,_,_=runtime.visit(kit,loc,work,repo,env,cmd,want,score=False,cold=phase=="empty-check-old",observe=False)
                need(before==study.source_state(repo,rev,bad),"actual source changed")
                save(loc/"source.json",before)
                rows=replay.cargo_rows((loc/"outer.stdout").read_bytes());products=study.results(rows,not bad)
                owners=[r for r in rusts if r["kind"]=="full" and r["name"]=="ruff_workspace"]
                need(len(owners)==int(phase!="repeat-build-new") and (phase!="repeat-build-new" or counts=={"rustc":[],"linkers":[]}),
                     ("unexpected ordinary check/build root roster",phase,counts))
                if owners:
                    flags=owners[0]["argv"];output=next(a.split("=",1)[1].split(",") for a in flags if a.startswith("--emit="))
                    need(("link" in output)==(cmd==build) and "metadata" in output,"wrong real check/build compiler mode")
                selected=tracking.read(loc,kit.sdk);save(loc/"source-selection.json",selected)
                if cmd==check or role=="P":need(not selected["renames"],"check or parent reused a codegen object")
                row={"argv":cmd,"returncode":want,"roster":counts,"source":before,"kernel":sha(loc/"kernel.json"),"selection":sha(loc/"source-selection.json")}
                if cmd==build:
                    reader=pilot.native.client(loc,rows,products,suite/"consumer",work,env,gold[rev],kit.evidence/"native-bodies")
                    reference=refs[role]["old" if rev==study.OLD else "clean-new"]
                    archive=study.artifact(products,study.OWNER)
                    obj=support.physical.keep(archive,kit.evidence/"owner-archives",b"!<arch>\n")
                    gold_sha=reference["owner_archive"]["sha256"]
                    with gzip.open(kit.evidence/"owner-archives"/(gold_sha+".gz"),"rb") as f:expected=durable.member_map(f.read())
                    need(durable.member_map(archive.read_bytes())["objects"]==expected["objects"] and reader["sha256"]==reference["elf"],"metadata transition produced different complete CGU or reader")
                    row.update(reader=reader["sha256"],archive=obj["sha256"],reference=gold_sha)
                if bad:row["error"]="E0308"
                save(loc/"transition.json",row);visits[phase]=sha(loc/"transition.json")
            terminal[role]=visits
    save(out/"complete.json",terminal)
