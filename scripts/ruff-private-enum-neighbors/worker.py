"""One ordinary, unscored P3/Q3 stock-Cargo structural acquisition."""
import ast
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import traceback
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-ruf009-derived-enum"))
import case
import metadata

w, old, historical = case.w, case.old, case.historical
R, OUT = case.ROOT, case.BASE
PLAN = json.loads((HERE / "plan.json").read_bytes())
sha, save, need = case.sha, case.save, case.need
GIB = 1 << 30
DEFAULTS = ["--locked", "--offline", "-j4", "--message-format=json"]
ERROR = b'\nconst OHM_NEIGHBOR_E0308: u32 = "invalid";\n'


def source(c, point):
    rec = c["sources"][point]
    subprocess.run(["git", "-C", w.SRC, "checkout", "-q", "--detach", rec["commit"]], check=True)
    need(w.git(w.SRC, "rev-parse", "HEAD^{tree}") == rec["tree"] and
         not w.git(w.SRC, "status", "--porcelain", "--untracked-files=all") and
         sha(w.SRC / "Cargo.lock") == rec["lock_sha256"] and
         all(sha(w.SRC / n) == h for n, h in rec["source"].items()), "literal Ruff sources")


def remove_owned(name):
    path = R / name
    need(path.parent == R and not path.is_symlink(), "private owned staging path")
    if path.exists():
        need(path.is_dir(), "only an owned directory may be reset")
        shutil.rmtree(path)


def reset(series):
    for name in ("state", "home", "temp", "cargo"):
        remove_owned(name)
        (R / name).mkdir()
    seed = R / ("seed-" + series)
    for key in ["registry/cache", "registry/index", "git/db", "git/checkouts"]:
        donor = seed / key
        if donor.is_dir():
            dst = R / "cargo" / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", "-a", "--reflink=auto", donor, dst], check=True)
    need(not any((R / "state").iterdir()), "independently empty target and shared build")


def acquire():
    R.mkdir()
    OUT.mkdir()
    (OUT / "members").mkdir()
    w.BRANCH = PLAN["branch"]
    w.checked_head()
    ram, disk = w.resources()
    need(ram >= 9.25*GIB and disk > 75*GIB, "entry floor")
    run = int(os.environ["GITHUB_RUN_ID"])
    job, = case.artifacts.api(f"actions/runs/{run}/attempts/1/jobs")["jobs"]
    info = case.artifacts.api(f"actions/runs/{run}")
    need(job["name"] == "Two real Ruff checks" and job["runner_name"] == os.environ["RUNNER_NAME"]
         and job["runner_id"] > 0 and info["head_sha"] == os.environ["REVIEWED_HEAD"], "physical worker")
    save(OUT/"worker.json", dict(run=run, job=job["id"], head=info["head_sha"],
         boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(), plan=PLAN, entry=[ram,disk]))
    bind = json.loads((case.HERE / "factory.json").read_bytes())
    need(bind["run"] == PLAN["factory"] and bind["source"] == PLAN["source_commits"], "registered factory")
    kit = old.scope_matched.kit("ruf009", bind)
    client = historical.cargo_client(R, OUT, case.artifacts)
    need(sha(client) == PLAN["cargo"], "literal common Cargo")
    roles = {}
    with zipfile.ZipFile(R/"scope-kit-ruf009/receipts.zip") as z:
        for role, label, arm in [("P","parent","normal"),("C","candidate","defer")]:
            donor = Path(kit["arms"][arm]["root"])
            driver, = (donor/"lib").glob("librustc_driver-*.so")
            guard = json.loads(z.read("scope-guard-"+label+".json"))
            need(sha(driver) == PLAN["driver"][role] == guard["driver_sha256"] and
                 hashlib.sha256(z.read("scope-evidence-"+label+".tar.gz")).hexdigest() == bind["guard_archives"][role],
                 "source-attested driver and native guard")
            sdk,files = historical.with_client(donor,R,arm,client,kit["arms"][arm]["files"])
            roles["inline-"+role] = dict(source=bind["source"][role],sdk=str(sdk),driver=sha(driver),
                                         rustc=sha(donor/"bin/rustc"),cargo=sha(client),files=files)
    save(OUT/"scope-sdks.json",roles)
    proxy = R/"proxies"; proxy.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    shutil.copy2(rustup,proxy/"rustup")
    need(sha(rustup)==sha(proxy/"rustup"),"physical rustup")
    for name in ["cargo","rustc","rustdoc"]:
        (proxy/name).symlink_to("rustup")
    for name in ["home","temp","rustup/toolchains","cargo","state"]:
        (R/name).mkdir(parents=True)
    (R/"rustup/toolchains/ohm").symlink_to(w.SDK)
    (R/"rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')


def prefetch(name, c):
    w.SRC = w.WS / name
    source(c,"new")
    need(w.git(w.SRC,"rev-parse","HEAD^") == c["sources"]["old"]["commit"],"actual parent")
    old.activate("P")
    e=case.env();e.pop("CARGO_NET_OFFLINE");e["CARGO_HOME"]=str(R/("seed-"+name))
    w.run(["cargo","+ohm","fetch","--locked"],e,OUT/("fetch-"+name),timeout=1200)
    lock=tomllib.loads((w.SRC/"Cargo.lock").read_text())["package"]
    known={p["name"]+"-"+p["version"]+".crate":p["checksum"] for p in lock if p.get("source","").startswith("registry+")}
    materialized={}
    for f in (Path(e["CARGO_HOME"])/"registry/cache").glob("*/*.crate"):
        digest=sha(f)
        need(known.get(f.name)==digest,"source archive or lock mismatch for "+f.name)
        materialized[f.name]=digest
    need(materialized,"fresh locked crate materialization")
    save(OUT/("registry-"+name+".json"),materialized)


def member(raw,suffix):
    h=hashlib.sha256(raw).hexdigest()
    p=OUT/"members"/(h+"."+suffix+".zst")
    if not p.exists():
        with p.open("xb") as o:
            subprocess.run(["zstd","-q","-3","-c"],input=raw,stdout=o,check=True)
    return h


def traces(directory,role):
    rows=[]
    driver,=(w.SDK/"lib").glob("librustc_driver-*.so")
    need(sha(driver)==PLAN["driver"][role],"wrong executing driver")
    full=directory/"kernel.jsonl.gz"
    with gzip.open(full,"wt",compresslevel=3) as out:
        for f in sorted(directory.glob("trace.*")):
            tid=int(f.name.rsplit(".",1)[1])
            argv=None; opens=[]
            for s in f.read_text(errors="replace").splitlines():
                if s.startswith("execve(") and s.endswith(" = 0"):
                    out.write(json.dumps([tid,s])+"\n")
                    m=re.match(r'execve\(("(?:\\.|[^"\\])*"), (\[.*\]), (?:0x|NULL|\[)',s)
                    if '"--crate-name"' not in s:continue
                    need(m,"unparsed kernel compiler argv")
                    exe=Path(ast.literal_eval(m[1]));args=ast.literal_eval(m[2])
                    if exe.is_file() and exe.samefile(R/"proxies/rustup"):continue
                    need(argv is None and exe.is_absolute() and exe.samefile(w.SDK/"bin/rustc"),"unbound compiler")
                    argv=args
                elif driver.name in s and s.startswith("openat(") and re.search(r'= [0-9]+',s):
                    out.write(json.dumps([tid,s])+"\n")
                    m=re.search(r'openat\([^,]+, "([^"]+)"',s)
                    if m and Path(m[1]).is_file() and Path(m[1]).samefile(driver):opens.append(s)
            if argv is not None:
                need(opens,"successful compiler driver open missing")
                rows.append(dict(tid=tid,crate=argv[argv.index("--crate-name")+1],argv=argv,driver=opens))
    # The complete source-owning execs and driver opens have already been serialized.
    for f in directory.glob("trace.*"):f.unlink()
    return rows


def cargo(c,label,out,role,argv,version,invalid=False):
    dest=out/label
    observer=out/(label+"-observer");observer.mkdir()
    args=["/usr/bin/strace","-ff","-qq","-s","260000","-e","trace=execve,openat","-o",str(observer/"trace"),*argv]
    w.run(args,case.env(),dest,expected=101 if invalid else 0)
    rows=traces(observer,role)
    stream=[json.loads(s)for s in (dest/"stdout").read_bytes().splitlines()]
    need([m["success"]for m in stream if m["reason"]=="build-finished"]==[not invalid],"typed Cargo terminal")
    errors=[m["message"] for m in stream if m["reason"]=="compiler-message" and m["message"]["level"]=="error"]
    if invalid:
        need(len(errors)==1 and (errors[0].get("code") or {}).get("code")=="E0308" and any(
             s["is_primary"] and s["file_name"]==c["error_source"] for s in errors[0]["spans"]), "actual source-bound E0308")
    else:need(not errors,"unexpected compiler error")
    typed=[m for m in stream if m["reason"]=="compiler-artifact"]
    external=sorted({(m["package_id"],m["target"]["name"])for m in typed if not str(m["manifest_path"]).startswith(str(w.SRC)+"/")})
    get_size=[(p,n) for p,n in external if "get-size" in p or "get_size" in n]
    save(dest/"kernel-observed.json", dict(actual=rows, external=external, get_size=get_size))
    snap={}
    if argv[2]=="check" and not invalid:
        for m in typed:
            name=m["target"]["name"]
            if name not in c["selected"] or "lib" not in m["target"]["kind"]:continue
            f,=[Path(x) for x in m["filenames"] if x.endswith(".rmeta")]
            raw=f.read_bytes(); decoded=metadata.table(raw,name,version,m["target"]["edition"])
            key=member(raw,"rmeta")
            found=member(json.dumps(decoded,sort_keys=True,separators=(",",":")).encode(),"rows")
            snap[name]=dict(file=str(f),full=key,public=decoded["header"]["public"],rows=found,count=len(decoded["rows"]))
        need(c["owner"]in snap,"no genuine producer metadata")
    info=dict(argv=argv,source=w.git(w.SRC,"rev-parse","HEAD"),actual=rows,external=external,get_size=get_size,metadata=snap,
              status=101 if invalid else 0,errors=errors,nominal=[m["target"]["name"] for m in typed if not m["fresh"]])
    save(dest/"observed.json",info)
    print(out.name,label,'physical '+','.join(r['crate'] for r in rows),flush=True)
    return info,typed


def physical_inputs(out, typed, source, env):
    inputs = {}
    for row in typed:
        is_local = str(row["manifest_path"]).startswith(str(w.SRC)+"/")
        for n in row["filenames"]:
            path=Path(n)
            if path.is_file():
                key=(row["package_id"],row["target"]["name"],",".join(row["target"]["kind"]),path.name)
                inputs["|".join(key)] = dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size,local=is_local)
    generated={}
    for line in (out/"stdout").read_bytes().splitlines():
        row=json.loads(line)
        if row["reason"]!="build-script-executed":continue
        directory=Path(row["out_dir"])
        for f in sorted(directory.rglob("*")):
            if f.is_file():
                key=row["package_id"]+"|"+str(f.relative_to(directory))
                generated[key]=dict(path=str(f),sha256=sha(f),bytes=f.stat().st_size)
    save(out/"physical-inputs.json",dict(artifacts=inputs,generated=generated,source=source))


def metadata_display(c,label,destination,info,env):
    v=info["metadata"].get(c["owner"])
    if not v:return
    shown=subprocess.check_output(["rustc","+ohm",v["file"],"-Zls=public_hash"],env=env,text=True).strip()
    need(shown=="Public hash: "+bytes.fromhex(v["public"])[::-1].hex(),"physical rmeta header reader")
    save(destination/label/"display.json",dict(raw=v["public"],native=shown,body=v["full"]))


def check_history(name,c,role,version,out):
    result={}
    argv=["cargo","+ohm","check",*c["selector"],*DEFAULTS]
    for phase,point in [("old","old"),("old-unchanged","old"),("edit","new"),
                        ("edited-unchanged","new"),("reverse","old"),("invalid","new"),
                        ("repair","new"),("empty-edited","new")]:
        if phase in ("old","empty-edited"):reset(name)
        source(c,point)
        path=w.SRC/c["error_source"]
        original=path.read_bytes()
        try:
            if phase=="invalid":path.write_bytes(original+ERROR)
            info,typed=cargo(c,phase,out,role,argv,version,phase=="invalid")
            result[phase]=info
            physical_inputs(out/phase,typed,info["source"],case.env())
            metadata_display(c,phase,out,info,case.env())
        finally:
            if phase=="invalid":
                path.write_bytes(original)
        source(c,point)
    return result


def native_history(name,c,role,version,out):
    result={}
    fixed = ["-p",c["package"],"--lib"] if name=="line-index" else ["-p",c["package"],"--example","character"]
    for phase,point in [("native-old","old"),("native-edit","new"),("native-reverse","old"),("native-empty-edited","new")]:
        if phase in ("native-old","native-empty-edited"):reset(name)
        source(c,point)
        argv=["cargo","+ohm","build",*fixed,*DEFAULTS]
        dest=out/phase
        w.run(argv,case.env(),dest)
        stream=[json.loads(line)for line in (dest/"stdout").read_bytes().splitlines()]
        need([v["success"]for v in stream if v["reason"]=="build-finished"]==[True],"native Cargo terminal")
        typed=[v for v in stream if v["reason"]=="compiler-artifact"]
        physical_inputs(dest,typed,c["sources"][point]["commit"],case.env())
        if name=="line-index":
            owner,=[v for v in typed if v["target"]["name"]==c["owner"] and v["target"]["kind"]==["lib"]]
            rlib,=[Path(n)for n in owner["filenames"]if n.endswith(".rlib")]
            directories=sorted({str(Path(n).parent)for v in typed for n in v["filenames"] if n.endswith((".rlib",".so"))})
            exe=R/"line-end-reader"
            args=["rustc","+ohm",HERE/"line-reader.rs","--edition=2024","--extern",c["owner"]+"="+str(rlib)]
            # The Ohm build tree stores each package's release artifacts in its own directory.
            for directory in directories:args.extend(["-L","dependency="+directory])
            args.extend(["-o",exe])
            w.run(args,case.env(),dest/"reader-link")
            probes=[];expected=(b"2\n1\n1\n" if point=="old" else b"1\n1\n1\n")
        else:
            row,=[v for v in typed if v["target"]["kind"]==["example"] and v["target"]["name"]=="character"]
            exe=Path(row["executable"])
            probes=["LATIN CAPITAL LETTER A","latinSMALLletterA","NO SUCH OHM CHARACTER"]
            expected=b"A\n"+(b"a\n" if point=="old" else b"latinSMALLletterA: no such character\n")+b"NO SUCH OHM CHARACTER: no such character\n"
        runtime=subprocess.run([exe,*probes],env=case.env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        raw=exe.read_bytes();info=dict(argv=argv,exe=member(raw,"elf"),bytes=len(raw),args=probes,
            stdout=runtime.stdout.decode(),stderr=runtime.stderr.decode(),exit=runtime.returncode,expected=expected.decode())
        save(dest/"native.json",info)
        need(raw[:4]==b"\x7fELF" and runtime.returncode==0 and runtime.stdout==expected and not runtime.stderr,
             "ordinary native behavior at "+phase)
        result[phase]=info
    return result


def summary(c,series,native,role):
    def names(phase):return [v["crate"]for v in series[phase]["actual"]]
    def src(phase):return series[phase]["metadata"][c["owner"]]
    def compact(phase):return {n:(v["full"],v["public"],v["rows"])for n,v in series[phase]["metadata"].items()}
    edit=src("edit");oldmeta=src("old"); cmd=[v["argv"] for v in series["edit"]["actual"] if v["crate"]==c["owner"]]
    selection=[n for n in c["selected"]if n!=c["owner"]]
    return dict(role=role,old=oldmeta,edited=edit,owner_edit=bool(cmd),owner_argv=cmd,
        selected=selection,actual={p:names(p)for p in series},
        edited_downstream=sorted(n for n in names("edit")if n in selection),
        get_size={p:v["get_size"]for p,v in series.items()},
        exact_metadata=dict(own_empty=compact("edit")==compact("empty-edited"),
            repair=compact("edit")==compact("repair"),reverse=compact("old")==compact("reverse"),
            edited_settled=compact("edit")==compact("edited-unchanged"),old_settled=compact("old")==compact("old-unchanged")),
        native_elf={p:v["exe"] for p,v in native.items()},
        native_empty=native["native-edit"]["exe"]==native["native-empty-edited"]["exe"],
        native_reverse=native["native-old"]["exe"]==native["native-reverse"]["exe"],
        invalid=series["invalid"]["status"]==101)


def main():
    acquire(); results={}; failures={}
    for name,roles in [("line-index","PC"),("unicode","CP")]:
        c=PLAN["cases"][name];w.SRC=w.WS/name
        try:prefetch(name,c)
        except Exception:
            failures[name+"-acquire"]=traceback.format_exc();save(OUT/"exceptions.json",failures);continue
        for role in roles:
            out=OUT/(name+"-"+role);out.mkdir()
            try:
                history=old.activate(role)
                save(out/"activated.json",history)
                version=subprocess.check_output(["rustc","+ohm","--version"],env=case.env(),text=True).strip()+" (Ohm metadata 3)"
                series=check_history(name,c,role,version,out)
                save(out/"check-history.json",{k:{"actual":[r["crate"]for r in v["actual"]],"metadata":v["metadata"],"get_size":v["get_size"],"exit":v["status"]}for k,v in series.items()})
                native=native_history(name,c,role,version,out)
                row=summary(c,series,native,role);results.setdefault(name,{})[role]=row
                save(out/"complete.json",row)
            except Exception:
                failures[name+"-"+role]=traceback.format_exc()
                print(failures[name+"-"+role],flush=True)
            save(OUT/"exceptions.json",failures)
    save(OUT/"complete.json",dict(scope="unscored structural, two original Ruff transitions",result=results,
         refusals=failures,scored_pairs=0,pmu=False,confirmation_workers=0))
    need(not failures and set(results)==set(PLAN["cases"])and all(set(v)=={"P","C"}for v in results.values()),
         "incomplete native structural worker; original reasons retained")


if __name__=="__main__":main()
