"""Enroll two separately authenticated production compilers, preserving the prior control's own paired qualification."""
import shutil
import subprocess
import sys
import core as c
import production_archive as archive
from production_service import REPO, PRODUCERS, service
m=c.m

def admit():
    w,tmp=c.host(); _,previous=m.check_sources(w); old=m.load("signed_release_intake",previous/"intake.py")
    out=w/"trait-results";proof=out/"intake";proof.mkdir();meta=proof/"role-material";meta.mkdir()
    temp=tmp/"production-callable-incoming";temp.mkdir();pool=tmp/"ctfe22-root-sdks";pool.mkdir()
    old.released(temp,proof)
    (signed,)=(temp/"signed").glob("*.tar.gz")
    fixed=archive.official_cargo(signed,temp)
    ctrl,treat=c.ROLES
    control=m.read(c.HERE/"verified-control-lock.json")
    seals=m.read(c.HERE/"original-control.json")
    result={}
    for role in c.ROLES:
        p=PRODUCERS[role];arm=c.PAIR["arms"][role];here=proof/role;here.mkdir();work=temp/role;work.mkdir()
        docs=[]
        for file,tail in [("run",""),("jobs","/attempts/1/jobs?per_page=100"),("artifacts","/artifacts?per_page=100")]:
            row=old.gh_json("api",f"repos/{REPO}/actions/runs/{p['run']}"+tail)
            m.save(here/(file+".json"),row);docs.append(row)
        live=service(role,*docs,control)
        c.guard(live==arm["service"] and live["members"][p["sdk"]]==arm["artifact"],"SDK service changed after registration")
        items={}
        for kind in ("sdk","qa")+(("prior_pair",)if role==ctrl else ()):
            name=p[kind];a=live["members"][name];f=work/(kind+".zip")
            old.gh_bytes(f"repos/{REPO}/actions/artifacts/{a['id']}/zip",f,a["bytes"],a["sha256"])
            items[kind]=work/kind
            archive.unpack(f,items[kind],kind)
        scratch=work/"restored";scratch.mkdir()
        builder=w/("control-builder" if role==ctrl else "treatment-builder")
        subprocess.run([sys.executable,"-ISBu",c.HERE/"verify_role.py",role,builder,items["sdk"],items["qa"],scratch,fixed,meta/role,pool],check=True)
        if role==ctrl:
            prior=items["prior_pair"]
            for src,dst in [(prior/"passed.json","pair-passed.json"),(prior/"cache-transition/passed.json","cache-transition.json")]:
                shutil.copyfile(src,proof/dst)
            for path,digest in seals["files"].items(): c.guard(m.filesha(proof/path)==digest,"control differs from the previous independently enrolled distribution")
            pair=m.read(proof/"pair-passed.json");transition=m.read(proof/"cache-transition.json")
            c.guard(pair["roles"][ctrl]=={k:m.read(meta/ctrl/(k+".json")) for k in ("source","role")} and pair["cross_sdk_cache_rejection_sha256"]==m.filesha(proof/"cache-transition.json")
                    and transition["native_processes"]==16 and pair["required_benchmark_cargo_sha256"]==m.filesha(fixed)
                    and all(pair["artifacts"][ctrl][k]=={x:live["members"][p[k]][x]for x in ("id","sha256")}for k in ("sdk","qa")), "wrong original paired qualification")
        result[role]=m.read(meta/role/"registered.json")
    a,b=(m.read(meta/r/"source.json")for r in c.ROLES)
    x,y=(m.read(meta/r/"role.json")for r in c.ROLES)
    c.guard(all(a[k]==b[k] for k in ("recipe","training_objects","component_git","released_coordinator","signed_manifest_sha256")) and
            x["execution_pgo"]==y["execution_pgo"] and x["bolt_note"] is y["bolt_note"] is True and x["driver"]["sha256"]!=y["driver"]["sha256"]
            and x["archive_sha256"]!=y["archive_sha256"] and x["effective_benchmark_cargo_sha256"]==y["effective_benchmark_cargo_sha256"]==m.filesha(fixed),
            "not a matched production compiler pair")
    m.save(out/"intake.json",{"installed":result,"sdk_lock_sha256":m.filesha(c.HERE/"pair.json"),"signed_cargo_sha256":m.filesha(fixed)})

def migration():
    import foreign
    foreign.gate()
