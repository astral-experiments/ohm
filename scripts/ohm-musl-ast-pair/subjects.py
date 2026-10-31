"""Build the exact compiler change, test both readers of its new cases, and seal one SDK plus a driver."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/"ohm-musl-ast")]
import sdk as s
import rustdoc_audit as docaudit

SOURCE=json.loads((HERE/"source.json").read_text())
PREVIOUS=json.loads((HERE/"parent.json").read_text())
P=SOURCE["reviewed_parent"]
C=SOURCE["reviewed_source"]
FRONT="bin/rustc"
DRIVER=s.ORIGINAL["driver_path"]
ROOT=s.rt.ROOT
STAGE=ROOT/"rust"/"build"/s.rt.HOST/"stage1"
LOG=s.DEST/"pair-receipts"
PACK=s.DEST/"pair-transfer"
STRICT="761ea115605c34f11a1cd29afd68812c1e1359dd"
SIGNED="2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"
AWARE=s.SEAL["cargo"]["git"]
OLD={"signed":("4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e",SIGNED),
     "strict":("035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4",STRICT)}
REF="charlie/qa-musl-ast-reviewed-compiler"


def legacy():
    repo="repos/astral-experiments/ohm/"
    api=lambda name:json.loads(subprocess.check_output(["gh","api",repo+name]))
    assert not any((PACK/n).exists() for n in ("strict-cargo.zst","signed-cargo.zst"))
    signed=api("releases/429373023");assert signed["tag_name"]=="ohm-1.99.0-21" and not signed["draft"]
    a,=[v for v in signed["assets"] if v["id"]==693058648]
    name="ohm-1.99.0-21-x86_64-unknown-linux-gnu.tar.gz"
    digest="6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4"
    assert (a["name"],a["size"],a["digest"])==(name,359657153,"sha256:"+digest)
    scratch=s.DEST/"original-readers";scratch.mkdir()
    subprocess.run(["gh","release","download",signed["tag_name"],"--repo","astral-experiments/ohm","--dir",scratch,"--pattern",name],check=True)
    assert s.sha(scratch/name)==digest
    found=[]
    with tarfile.open(scratch/name,"r|gz") as tar:
        for member in tar:
            if Path(member.name).parts[1:]==("cargo","bin","cargo"):
                assert member.isreg()
                with (scratch/"signed").open("xb") as out:shutil.copyfileobj(tar.extractfile(member),out)
                found.append(member.name)
    assert len(found)==1
    run=api("actions/runs/41151297839")
    assert (run["head_sha"],run["event"],run["run_attempt"],run["status"])==("f23a67771c625785cd70f58e9b46e8d26af3d317","workflow_dispatch",1,"completed")
    job=api("actions/jobs/124388202956");assert job["run_id"]==run["id"] and job["name"]=="builder" and job["conclusion"]=="success"
    def grab(id_,bytes_,want):
        art=api("actions/artifacts/"+str(id_))
        assert (art["workflow_run"]["id"],art["workflow_run"]["head_sha"],art["digest"],art["size_in_bytes"],art["expired"])==(run["id"],run["head_sha"],"sha256:"+want,bytes_,False)
        path=scratch/(str(id_)+".zip")
        with path.open("xb") as out:subprocess.run(["gh","api",repo+"actions/artifacts/"+str(id_)+"/zip"],stdout=out,check=True)
        assert s.sha(path)==want
        return zipfile.ZipFile(path)
    with grab(13023471212,17661123,"9a259bfc8b82d2bbf67d7d45b01c56902e8e4eff7654cc34d1537881868a76c2") as z:
        assert set(z.namelist())=={"cargo","build.json"}
        (scratch/"strict").write_bytes(z.read("cargo"))
        embedded=z.read("build.json")
    art=api("actions/artifacts/13023271637")
    with grab(art["id"],art["size_in_bytes"],"c3316118ecb13fd54259b7ae760f9daccb978ee0acd39437404dfcec654a3eff") as z:
        receipt=z.read("build.json")
    assert receipt==embedded and hashlib.sha256(receipt).hexdigest()=="d54bc38a259b60b17168c745fa19389d81f9d861b7be42ef04e09b4de4e8ea4c"
    declared=json.loads(receipt)
    assert declared["candidate"]==STRICT and declared["qa"]==run["head_sha"] and declared["compiled"]==declared["delivered"]==OLD["strict"][0]
    (LOG/"strict-cargo-build.json").write_bytes(receipt)
    products={}
    for key,(digest,rev) in OLD.items():
        f=scratch/key;assert s.sha(f)==digest
        f.chmod(0o755);vv=subprocess.check_output([f,"-Vv"],text=True)
        assert "commit-hash: "+rev+"\n" in vv, vv
        subprocess.run(["zstd","-q","-3",f,"-o",PACK/(key+"-cargo.zst")],check=True)
        products[key]={"source":rev,"sha256":digest,"version":vv,"bytes":f.stat().st_size}
    s.save(LOG/"legacy-cargos.json",products)


def git(*args, data=None):
    return s.bc.git(ROOT/"rust",*args,data=data)


def runmake(label, expected):
    args=["test","--stage","1","-j8","--host",s.rt.HOST,"--target",s.rt.HOST,"tests/run-make/ohm-checked-dep-info"]
    try:
        s.bc.stage(args,"cmp-"+label+"-run-make")
        rc=0
    except subprocess.CalledProcessError as exc:
        rc=exc.returncode
    log=s.rt.LOG/("cmp-"+label+"-run-make.log")
    text=log.read_text(errors="replace")
    assert rc==expected,(label,rc,text[-2500:])
    if expected:
        assert "rmake.rs:229:" in text and "assertion `left == right` failed" in text
        assert "/dev/null/ohm-untracked-relink-inputs:" in text and "left: false" in text and "right: true" in text
    else:
        assert "ohm-checked-dep-info" in text and "1 passed" in text, text[-4000:]
    s.save(LOG/(label+"-run-make.json"),{"status":rc,"source":git("rev-parse","HEAD"),"compiler":git("rev-parse","HEAD:compiler"),"command":args,"log":s.sha(log)})


def inventory(root):return s.rows([k for k in root.rglob("*") if k.is_file()],root)


def build():
    assert (LOG/"legacy-cargos.json").is_file() and set(p.name for p in PACK.iterdir())=={"signed-cargo.zst","strict-cargo.zst"}
    assert s.sha(HERE/"positions.json")=="2afef068002e7a4da305d2f937003d6b3bccd0aaf308000916631b3688e73da1"
    assert s.sha(s.HERE/"PLAN.md")=="f5d5776020bee6e1d08980e891aa38410a8c4b6fe1fb39746784e9a438eba57a"
    assert inventory(s.rt.SDK)==PREVIOUS["files"] and len(PREVIOUS["files"])==183
    assert git("rev-parse","HEAD")==SOURCE["qa_parent"] and git("rev-parse","HEAD^{tree}")==SOURCE["qa_parent_tree"]
    # Freeze the enrolled P SDK independently of any subsequently overwritten bootstrap file.
    for n in PREVIOUS["files"]:
        dest=s.rt.SDK/n
        if dest.stat().st_nlink>1:
            tmp=dest.with_suffix(dest.suffix+".freezing");shutil.copy2(dest,tmp);tmp.replace(dest)
    assert inventory(s.rt.SDK)==PREVIOUS["files"]
    subprocess.run(["tar","--zstd","--hard-dereference","-cf",PACK/"base-sdk.tar.zst","-C",s.rt.SDK,*sorted(PREVIOUS["files"])],check=True)
    patch=(HERE/"candidate.patch").read_bytes()
    assert hashlib.sha256(patch).hexdigest()==SOURCE["patch_sha256"]
    git("apply","--index","--binary","--include=tests/**","-",data=patch)
    assert set(git("diff","--cached","--name-only").splitlines())=={n for n in SOURCE["paths"] if n.startswith("tests/")}
    runmake("P",1)
    git("apply","--index","--reverse","--binary","--include=tests/**","-",data=patch)
    assert not git("status","--porcelain","--untracked-files=no")
    git("apply","--index","--binary","-",data=patch)
    assert git("write-tree")==SOURCE["source_result"]
    # Preserve the measured parent object; a constructed QA commit stores only the reviewed tree delta.
    author="Ohm QA <qa@example.invalid> 1793404800 +0000"
    body=(f'tree {SOURCE["source_result"]}\nparent {SOURCE["qa_parent"]}\nauthor {author}\ncommitter {author}\n\nApply exact reviewed musl register barrier recognition\n').encode()
    candidate=git("hash-object","-w","-t","commit","--stdin",data=body)
    git("update-ref","--no-deref","HEAD",candidate,SOURCE["qa_parent"])
    assert git("rev-parse","HEAD:compiler")==SOURCE["compiler"] and git("rev-parse","HEAD:library")==SOURCE["library"]
    for n,want in SOURCE["paths"].items():assert git("rev-parse","HEAD:"+n)==want
    out={};parent=PREVIOUS["files"]
    musl_opts=[f"target.{s.MUSL}.{k}={v}" for k,v in (("musl-libdir",str(s.DEST/"rust-1.99-musl-native")),("cc","/usr/bin/musl-gcc"),
            ("cxx","/usr/bin/musl-gcc"),("ar","/usr/bin/ar"),("linker","/usr/bin/musl-gcc"))]
    product=PACK/"driver-C.zst"
    fresh_doc=s.DEST/"independent-rustdoc-C"
    for part,triple,what,opts in (("host",s.rt.HOST,["compiler/rustc","library"],[]),("rustdoc",s.rt.HOST,["src/tools/rustdoc"],[]),
                                   ("gnu",s.rt.TARGET,["library"],[]),("musl",s.MUSL,["library"],musl_opts)):
        args=[*[v for opt in opts for v in ("--set",opt)],"build","--stage","1","-j8","--host",s.rt.HOST,"--target",triple,*what]
        s.bc.stage(args,"cmp-C-"+part)
        if part=="rustdoc":files=[STAGE/"bin/rustdoc",STAGE/DRIVER]
        else:files=s.rt.inventory(STAGE,triple)
        rows=s.rows(files,STAGE)
        extra={n:[parent.get(n),row] for n,row in rows.items() if row!=parent.get(n) and n!=DRIVER}
        s.save(LOG/("C-"+part+"-source-components.json"),{"target":triple,"source":candidate,
               "all":rows,"parent_driver":parent[DRIVER],"different_non_driver":extra})
        # Preserve complete divergent files up to a bounded 128 MiB, as well as every member's hashes.
        remaining=128*1024*1024
        for n,(old,new) in extra.items():
            if old is None or max(old[1],new[1])>remaining:continue
            for source_file,row in [(s.rt.SDK/n,old),(STAGE/n,new)]:
                dest=LOG/"different-members"/(row[0]+".zst");dest.parent.mkdir(exist_ok=True)
                if not dest.exists():subprocess.run(["zstd","-q","-3",source_file,"-o",dest],check=True)
            remaining-=max(old[1],new[1])
        if part=="rustdoc":
            assert list(extra)==["bin/rustdoc"]
            shutil.copy2((STAGE/"bin/rustdoc").resolve(strict=True),fresh_doc)
            original=s.rt.SDK/"bin/rustdoc"
            def source_line(role,line):
                rev=SOURCE["qa_parent"] if role=="P" else candidate
                return git("show",rev+":"+docaudit.FILE).splitlines()[line-1].strip()
            s.save(LOG/"rustdoc-elf-audit.json",docaudit.audit(original.read_bytes(),fresh_doc.read_bytes(),source_line))
            # The independent candidate documenter above is retained and exercised. Both operational kits use P's original rustdoc.
            rows["bin/rustdoc"]=parent["bin/rustdoc"]
        else:assert not extra,extra
        for n,v in rows.items():assert v==out.setdefault(n,v),n
        assert rows[DRIVER]!=parent[DRIVER]
        if part=="host":subprocess.run(["zstd","-q","-3",STAGE/DRIVER,"-o",product],check=True)
    out|={n:parent[n] for n in s.rt.TOOLS}
    assert set(out)==set(parent) and [n for n,v in out.items() if v!=parent[n]]==[DRIVER]
    assert inventory(s.rt.SDK)==parent
    assert s.sha(STAGE/DRIVER)==out[DRIVER][0] and s.sha(fresh_doc)==docaudit.C_DOC
    docaudit.exercise(s.rt.SDK,parent,DRIVER,(STAGE/DRIVER).resolve(strict=True),fresh_doc,s.DEST/"rustdoc-quadrants",LOG/"rustdoc-quadrants",
                      s.MUSL,s.save)
    assert inventory(s.rt.SDK)==parent
    runmake("C",0)
    archive={n:[s.sha(p),p.stat().st_size] for p in PACK.iterdir() if p.is_file() for n in [p.name]}
    s.save(PACK/"identity.json",{"run":int(os.environ["GITHUB_RUN_ID"]),"head":os.environ["GITHUB_SHA"],"attempt":int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "sha256":archive,"base":parent,"candidate_driver":out[DRIVER],"legacy":OLD,"source":SOURCE,"synthetic_candidate":candidate,
        "previous_parent_seal":s.sha(HERE/"parent.json"),"rustdoc":{"operational":parent["bin/rustdoc"],"fresh_candidate":docaudit.C_DOC,
        "comparison":s.sha(LOG/"rustdoc-elf-audit.json"),"four_native_combinations":s.sha(LOG/"rustdoc-quadrants/terminal.json")}})
    s.save(LOG/"qualified.json",{"roles":{"P":parent,"C":out},"source":SOURCE,"reactivation":candidate,"products":archive})


if __name__=="__main__":
    if sys.argv[1:]==["legacy"]:
        LOG.mkdir(parents=True); PACK.mkdir(parents=True)
        legacy()
    else:
        assert sys.argv[1:]==["build"]
        build()
