"""Native signed and source-integrated Cargo on one immutable signed compiler and Ruff data generator."""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from execs import ExecTrace
from local_dev import observe
from measure import capture, fresh, native_rows, retire
from study import CARGO_SOURCE, TRIPLE, check_host, compress_bytes, digest, env_for, git, load, need, physical, run, save, sha, text_git
from versioned_select import AWARE

RUFF="93526150df078af7dd8fc4226cdcc469539d2001"
SUBTREE="6204e19cfc0fc74f827f8bd5d2f7d807d7045272"
LOCKBLOB="a07ef6fbbdf04d9a20e53f647dbccd47d6d93b75"
SUBJECTS={"signed":CARGO_SOURCE,"integrated":AWARE}
PHASES=("cold","first","repeat","edit","edit-repeat","empty-edit","bad","repair")
READER='fn main(){ for n in ["NULL","OHM CHANGED CONTROL","NUL"] { println!("{:?}", unicode_names2::character(n).map(u32::from)); } }\n'
CMD=["cargo","+ohm","build","-p","ruff_unicode_names2","--locked","--offline","-j4","--message-format=json"]
def verify_product(root):
    checker=load(root/"receipts/cargo-aware/product.json")
    actual={(n,sha(root/name)) for n,name in [("signed","signed/bin/cargo"),("integrated","cargo-aware")]}
    assert dict(actual)=={"signed":load(root/"receipts/release.json")["cargo"]["sha256"],"integrated":checker["binary"]["sha256"]}
    assert checker["source"]["commit"]==AWARE and checker["source"]["parents"]==[CARGO_SOURCE,"c18e91b514b2c4e4966c9ab03232c804af3e1b57"]
    return checker
def package(root):
    checker=verify_product(root)
    dest=root/"result-product";dest.mkdir()
    product=root/"cargo-aware";f=dest/"cargo.gz"
    with product.open("rb") as i,f.open("xb") as out,gzip.GzipFile(filename="",mode="wb",fileobj=out,compresslevel=5,mtime=0) as gz:
        shutil.copyfileobj(i,gz)
    with gzip.open(f,"rb") as inp: assert hashlib.file_digest(inp,"sha256").hexdigest()==sha(product)
    shutil.copy2(root/"receipts/cargo-aware/product.json",dest/"build.json")
    save(dest/"manifest.json",{"source":AWARE,"build_sha256":sha(dest/"build.json"),"bytes":product.stat().st_size,
        "sha256":sha(product),"compressed_sha256":sha(f),"release_sha256":load(root/"receipts/release.json")["archive"],
        "workflow":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"]})
def seed(root):
    repo=root/"unicode-ruff";trace=root/"receipts/unicode"
    run(["git","init","-q",repo]);git(repo,"remote","add","origin","https://github.com/astral-sh/ruff.git")
    git(repo,"fetch","--depth=1","--quiet","origin",RUFF);git(repo,"switch","--quiet","-c","qa-unicode",RUFF)
    assert text_git(repo,"rev-parse","HEAD")==RUFF and text_git(repo,"rev-parse","HEAD:crates/ruff_unicode_names2")==SUBTREE
    assert text_git(repo,"hash-object","Cargo.lock")==LOCKBLOB and not text_git(repo,"status","--porcelain")
    w=root/"unicode-fetch";env=env_for(w,root/"signed");env.pop("CARGO_NET_OFFLINE")
    run(["cargo","+ohm","fetch","--locked","--target",TRIPLE],cwd=repo,env=env,timeout=900)
    reg=w/"cargo-home/registry"; locked={r["name"]+"-"+r["version"]+".crate":r["checksum"] for r in tomllib.loads((repo/"Cargo.lock").read_text())["package"] if "checksum" in r}
    archives={str(p.relative_to(reg)):sha(p) for p in sorted(reg.glob("cache/*/*.crate"))}
    assert len(archives)>100 and all(locked[Path(k).name]==v for k,v in archives.items())
    ref=root/"unicode-seed";ref.mkdir();shutil.copytree(reg,ref/"registry")
    if (w/"cargo-home/git").is_dir():shutil.copytree(w/"cargo-home/git",ref/"git")
    save(trace/"sources.json",{"ruff":RUFF,"tree":text_git(repo,"rev-parse","HEAD^{tree}"),"subtree":SUBTREE,"lock":sha(repo/"Cargo.lock"),"archives":archives})
    return repo,ref
def selected(root,sdk,name):
    src=root/("signed/bin/cargo" if name=="signed" else "cargo-aware")
    temporary=sdk/"bin/cargo.selected";os.link(src,temporary);os.replace(temporary,sdk/"bin/cargo")
    v=run([sdk/"bin/cargo","-Vv"]).decode();assert "commit-hash: "+SUBJECTS[name] in v and (sdk/"bin/cargo").samefile(src)
    return {"cargo":physical(src),"version":v,"rustc":physical(sdk/"bin/rustc"),"driver":physical(next((sdk/"lib").glob("librustc_driver*.dylib")))}
def main(root):
    verify_product(root);repo,seed_dir=seed(root)
    sdk=root/"unicode-sdk";run(["/bin/cp","-cR",root/"signed",sdk],timeout=900)
    assert sha(sdk/"bin/rustc")==load(root/"receipts/release.json")["rustc"]["sha256"]
    top=root/"receipts/unicode"; script=repo/"crates/ruff_unicode_names2/build.rs"; data=script.parent/"data/NameAliases.txt"
    a=script.read_bytes();old=data.read_bytes();assert old.count(b"0000;NULL;control")==1
    changed=old.replace(b"0000;NULL;control",b"0000;OHM CHANGED CONTROL;control")
    source=root/"unicode-reader.rs";source.write_text(READER);exe=root/"unicode-reader";t=ExecTrace();t.ready();summary={}
    modes={}
    try:
        for name in SUBJECTS:
            who=selected(root,sdk,name)
            for explicit in (False,True):
                label=name+("-explicit" if explicit else "-host"); lane=top/label
                save(lane/"selection.json",who);work=root/"unicode-work";work.mkdir(exist_ok=True)
                fresh(work,seed_dir); gen={};summary[label]={}
                for phase in PHASES:
                    if phase=="edit":data.write_bytes(changed)
                    if phase=="bad":script.write_bytes(a+b"\nconst _: usize = UNKNOWN_OHM_UNICODE_294;\n")
                    if phase=="repair":script.write_bytes(a);data.write_bytes(old)
                    # Clean and warm share the same paths. Only their owned target/registry stores move.
                    out=lane/phase
                    def visit():
                        env=env_for(work,sdk);assert str(Path(run(["rustc","+ohm","--print","sysroot"],env=env).decode().strip()).resolve())==str(sdk.resolve())
                        cmd=CMD+(["--target",TRIPLE] if explicit else [])
                        status,so,se,events,streams=capture(cmd,repo,env,out,t);nf=native_rows(events,sdk)
                        assert nf["scope"]=="kernel-exec" and nf["cargo"]==1 and all(l["stock"] for l in nf["linkers"])
                        rows=[json.loads(l) for l in so.splitlines()]
                        ok=phase!="bad";assert status==(0 if ok else 101) and rows[-1]=={"reason":"build-finished","success":ok},(label,phase,status,se[-1000:])
                        facts={"work":nf,"status":status,"streams":streams,"command":cmd}
                        if not ok:
                            assert any((r["message"].get("code") or {}).get("code")=="E0425" and "UNKNOWN_OHM_UNICODE_294" in r["message"]["message"] for r in rows if r["reason"]=="compiler-message")
                            return facts
                        units=[r for r in rows if r["reason"]=="compiler-artifact"]
                        roster=sorted(json.dumps([r["package_id"],r["target"]["name"],r["target"]["kind"],r["features"],r["profile"]],sort_keys=True) for r in units)
                        if explicit not in modes:modes[explicit]=roster
                        assert len(roster)>=10 and roster==modes[explicit]
                        dirty=[r["target"]["name"] for r in units if not r["fresh"]]
                        unit,=[r for r in units if (r["target"]["name"],r["target"]["kind"])==("unicode_names2",["lib"])]
                        lib,=[Path(p) for p in unit["filenames"] if p.endswith(".rlib")]
                        outputs,=[Path(r["out_dir"]) for r in rows if r["reason"]=="build-script-executed" and r["package_id"]==unit["package_id"]]
                        gs={p.name:sha(p) for p in sorted(outputs.glob("*.rs"))};assert len(gs)==3
                        if phase in ("cold","empty-edit","edit","repair"):
                            assert "unicode_names2" in nf["full"]
                            observe(events,work,sdk,{"unicode_names2"},out)
                        if phase in ("first","repeat","edit-repeat"):
                            assert not dirty and not nf["full"] and not nf["link_only"] and not nf["linkers"],(label,phase,dirty,nf)
                        if phase=="edit":
                            # Cargo may rerun the declared generator program without recompiling build.rs.
                            assert any(Path(e["path"]).name.startswith(("build-script-build","build_script_build")) for e in events)
                        search=sorted({str(Path(f).parent) for r in units for f in r["filenames"]})
                        rc,rs,re,ev,st=capture(["rustc","+ohm","--edition=2021","--crate-name","unicode_reader",source,"--extern","unicode_names2="+str(lib),
                            *[x for d in search for x in ("-L","dependency="+d)],"-o",exe],repo,env,out/"reader-build",t)
                        assert rc==0 and exe.is_file(),re[-1000:]
                        proc=subprocess.run([exe],cwd=repo,env=env,capture_output=True,timeout=20)
                        edited=phase in ("edit","edit-repeat","empty-edit");want=b"None\nSome(0)\nSome(0)\n" if edited else b"Some(0)\nNone\nSome(0)\n"
                        compress_bytes(out/"reader.stdout.gz",proc.stdout);compress_bytes(out/"reader.stderr.gz",proc.stderr)
                        assert (proc.returncode,proc.stdout,proc.stderr)==(0,want,b"")
                        facts.update(typed=len(units),roster=digest(json.dumps(roster).encode()),dirty=dirty,generated=gs,
                            reader=physical(exe),archive=physical(lib),reader_stdout=proc.stdout.decode(),reader_exit=0)
                        gen[phase]=gs
                        return facts
                    if phase=="empty-edit":
                        from provider_edges import with_empty
                        facts=with_empty(work,lambda: empty_with_seed(work,seed_dir,visit))
                    else:facts=visit()
                    save(out/"verified.json",facts);summary[label][phase]=facts
                assert gen["cold"]==gen["first"]==gen["repeat"]==gen["repair"] and gen["edit"]==gen["edit-repeat"]==gen["empty-edit"]
                assert {n for n in gen["cold"] if gen["cold"][n]!=gen["edit"][n]}=={"generated_alias.rs"}
                assert text_git(repo,"status","--porcelain","--untracked-files=no")==""
                retire(work)
        for explicit in ("host","explicit"):
            for phase in PHASES:
                l=summary["signed-"+explicit][phase];r=summary["integrated-"+explicit][phase]
                assert l["status"]==r["status"] and l.get("generated")==r.get("generated") and l.get("reader_stdout")==r.get("reader_stdout")
        save(top/"terminal.json",{"cases":sum(map(len,summary.values())),"assignments":{k:{n:sha(top/k/n/"verified.json") for n in v} for k,v in summary.items()},"signed":CARGO_SOURCE,"integrated":AWARE})
    finally:t.close()
def empty_with_seed(work,seed,visit):
    # with_empty creates two empty transient build roots. The established
    # independent registry only supplies the pinned archives for the offline build.
    if not (work/"cargo-home/registry").exists():shutil.copytree(seed/"registry",work/"cargo-home/registry")
    return visit()
if __name__=="__main__":
    cmd,where=sys.argv[1:];root=Path(where).resolve()
    if cmd=="pack":package(root)
    else:assert cmd=="run";main(root)
