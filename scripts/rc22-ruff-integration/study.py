"""Unscored release-reader comparison on the two native programs changed by Ruff #28877."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
OLD = "4710e1aa962b13720cf64aa84eb279c5333896d7"
NEW = "915bb2b4bf9ae7eee47cf55646bbfebae254a23b"
TREES = {OLD: "81560f51b2974feba14a187071ced7f1a86a8f1a", NEW: "77cc553e8be94195bb5737a8ffda775c577ca113"}
LOCKS = {OLD: "3a079a64dd1783c6177fc86ca98238a65f4bc56e3e7a1ac8eb9cae2c5eba4ad9",
         NEW: "23e8dbc9a2f451fa819d63da20a9d3ca24de8b2ebda59c99930a8c0edc4044c7"}
CLI = ["cargo", "+ohm", "test", "-p", "ruff", "--test", "integration_test", "--no-run", "--locked", "--offline", "-j4", "--message-format=json"]
NAMES = {"ruff": ["bin"], "integration_test": ["test"]}
ADDED = "check_existing_at_paths_are_literal"
COMMON = "missing_argfile_reports_error"
STEPS = (("cold-A", OLD), ("settled-A", OLD), ("edit-B", NEW), ("settled-B", NEW), ("return-A", OLD), ("returned-settled-A", OLD))
NEW_STDOUT = (b"@list.py:1:8: F401 [*] \x60os\x60 imported but unused\n"
              b"@package/main.py:1:8: F401 [*] \x60sys\x60 imported but unused\n"
              b"Found 2 errors.\n[*] 2 fixable with the \x60--fix\x60 option.\n")
def need(ok, msg):
    if not ok: raise RuntimeError(str(msg))

def sha(path):
    with Path(path).open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()

def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x") as f: json.dump(obj, f, sort_keys=True, indent=2); f.write("\n")

def packed(p, body):
    with p.open("xb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", compresslevel=3, mtime=0) as stream:
            stream.write(body)

def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args])

def run(args, **kw):
    return subprocess.run(args, capture_output=True, check=False, timeout=90, **kw)

def trees(repo, rev):
    git(repo, "restore", "--source", rev, "--staged", "--worktree", "--", ".")
    need(git(repo, "write-tree").decode().strip() == TREES[rev] and git(repo, "diff", "--name-only") == b"" and
         sha(repo/"Cargo.lock") == LOCKS[rev] and git(repo, "rev-parse", "HEAD").decode().strip() == OLD, "Ruff tree/lock/HEAD")

def lockset(repo, rev):
    rows=tomllib.loads(git(repo,"show",rev+":Cargo.lock").decode())["package"]
    return {f"{p['name']}-{p['version']}.crate":p["checksum"] for p in rows if "checksum" in p}

def read_units(body):
    msgs = [json.loads(line) for line in body.splitlines()]
    need(msgs[-1] == {"reason":"build-finished","success":True}, "Cargo JSON did not finish successfully")
    rows = [m for m in msgs if m["reason"]=="compiler-artifact"]
    keys=[json.dumps([m["package_id"],m["target"]["name"],m["target"]["kind"],m["features"],m["profile"],m["filenames"]],
                     sort_keys=True) for m in rows]
    need(rows and len(set(keys))==len(keys), "ambiguous typed Cargo unit")
    selected={}
    for m in rows:
        target=m["target"]
        if target["name"] in NAMES and target["kind"]==NAMES[target["name"]] and m["executable"]:
            n=target["name"]
            need(n not in selected and m["profile"]["test"]==(n=="integration_test"), "ambiguous target")
            selected[n]=Path(m["executable"])
    need(set(selected)==set(NAMES), "Cargo did not return the CLI and integration test")
    return rows, selected

def check_cli(p, out, rev, env):
    case=out/"behavior"; case.mkdir()
    for n, data in {"@list.py":"import os\n","@package/main.py":"import sys\n",
                    "list.py":"--output-file\nsentinel.txt\nunrelated.py\n","package":"unrelated.py\n",
                    "unrelated.py":"","sentinel.txt":"unchanged\n"}.items():
        f=case/n; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(data)
    cmd=[p,"check","--isolated","--no-cache","--select","F401","--output-format","concise","@list.py","--","@package"]
    actual=run(cmd, cwd=case, env=env)
    sentinel=(case/"sentinel.txt").read_bytes()
    for k,v in [("stdout",actual.stdout),("stderr",actual.stderr),("sentinel",sentinel)]: (case/(k+".raw")).write_bytes(v)
    if rev==NEW:
        need((actual.returncode,actual.stdout,actual.stderr,sentinel)==(1,NEW_STDOUT,b"",b"unchanged\n"), "incorrect edited Ruff behavior")
    else:
        need(actual.returncode==0 and actual.stdout==actual.stderr==b"" and sentinel!=b"unchanged\n" and
             b"F401" not in sentinel, "baseline failed to reproduce the real argument-file behavior")
    return [actual.returncode,actual.stdout.hex(),actual.stderr.hex(),sentinel.hex()]

def inventory(test, binary, out, rev, repo, env):
    e={**env,"CARGO_BIN_EXE_ruff":str(binary),"CARGO_MANIFEST_DIR":str(repo/"crates/ruff"),"INSTA_UPDATE":"no"}
    got=run([test,"--list","--format","terse"],cwd=repo/"crates/ruff",env=e)
    (out/"list.txt").write_bytes(got.stdout); (out/"list.err").write_bytes(got.stderr)
    need(got.returncode==0 and not got.stderr,"native test listing")
    names=[line.removesuffix(": test") for line in got.stdout.decode().splitlines() if line.endswith(": test")]
    need(len(set(names))==len(names) and COMMON in names and (ADDED in names)==(rev==NEW), "native test identities")
    name=ADDED if rev==NEW else COMMON
    p=run([test,"--exact",name],cwd=repo/"crates/ruff",env=e)
    (out/"test.txt").write_bytes(p.stdout); (out/"test.err").write_bytes(p.stderr)
    need(p.returncode==0 and ("test "+name+" ... ok").encode() in p.stdout and b"1 passed; 0 failed" in p.stdout,
         ("failed named native integration test",name,p.stdout[-350:],p.stderr[-350:]))
    return sorted(names)

def emit_markers(rows, work, cas, role):
    import observe
    import plain
    result=[]
    for u in rows:
        n=u["target"]["name"]
        if n not in ("zmij","objc2") or u["target"]["kind"]!=["lib"] or not u["package_id"].startswith("registry+"): continue
        proof=plain.marker(u,work,cas)
        wanted=observe.evidence.V1 if n=="zmij" else observe.evidence.V2
        link=None if n=="zmij" and role=="pinned" else wanted
        need(proof["rules"]==[wanted] and proof["LNK1"]==link and proof["markers"]==([link] if link else []),"unexpected raw/translated native marker")
        result.append(proof)
    need(any("#zmij@1.0.10" in p["package"] for p in result),"real Ruff graph did not include the locked v1 producer")
    return result

def capture(trace, repo, env, out):
    rows=[]
    with (out/"cargo.stdout").open("xb") as stdout,(out/"cargo.stderr").open("xb") as stderr:
        try:
            code,_=trace.command(CLI,cwd=repo,env=env,out=stdout,err=stderr,timeout=2700,observed_rows=rows)
        finally:
            packed(out/"es-execs.json.gz",json.dumps(rows,separators=(",",":")).encode())
    need(code==0,("ordinary cargo failed",code))
    return rows, (out/"cargo.stdout").read_bytes()

def keep_image(root, p):
    key=sha(p); dest=root/"images"/(key+".zst")
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        subprocess.run(["zstd","-q","-3",str(p),"-o",str(dest)],check=True)
        with subprocess.Popen(["zstd","-q","-dc",dest],stdout=subprocess.PIPE) as z:
            need(hashlib.file_digest(z.stdout,"sha256").hexdigest()==key and z.wait()==0,"native custody readback")
    return key

def ld_output(argv):
    if argv[1:] in (["-v"], ["--version"], ["-version_details"], ["-help"], ["--help"]):
        return None
    paths=[Path(v) for k,v in zip(argv,argv[1:]) if k=="-o"]
    need(len(paths)==1,"unclassified Xcode ld invocation")
    return paths[0]

def native_outputs(native, selected):
    result={}
    for row in native["linkers"]:
        argv=row["argv"]
        p=ld_output(argv)
        if p is None:continue
        for name,exe in selected.items():
            if not re.fullmatch(re.escape(name)+r"(?:-[0-9a-f]{16})?",p.name): continue
            need(p.is_file() and (p.samefile(exe) or sha(p)==sha(exe)) and name not in result,
                 ("linker output and returned program differ",name,str(p),str(exe)))
            result[name]=(p,argv)
    return result

def bind_same_path(proof, output, argv):
    """Bind the saved module/input proof to the one physical Xcode link at this output."""
    owner=output.with_suffix(".rlink-objects")
    actual=[arg for arg in argv if Path(arg).parent==owner and arg.endswith(".o")]
    need(proof["source"]=="saved-rustc-recipe" and proof["output"]==str(output) and
         ld_output(argv)==output and actual and len(set(actual))==len(actual) and
         set(actual)==set(proof["physical"]),"actual Xcode ld and saved root objects differ")
    return {**proof,"source":"kernel-xcode-ld+rustc-recipe",
            "linker_argv":hashlib.sha256(json.dumps(argv,separators=(",",":")).encode()).hexdigest()}

def phase(root,repo,work,sdk,env,role,name,rev,trace,prior):
    import cgu_inputs,measure
    out=root/"receipts"/role/name;out.mkdir(parents=True)
    need(shutil.disk_usage(root).free>=14*1024**3,"less than 14 GiB of space before Cargo")
    ev,stdout=capture(trace,repo,env,out); units,selected=read_units(stdout)
    need(all(any(p.resolve().is_relative_to(work/n) for n in ("target","shared")) for p in selected.values()),"foreign promoted native output")
    nd=measure.native_rows(ev,sdk)
    need(nd["scope"]=="kernel-exec" and nd["cargo"]==1 and all(l["stock"] for l in nd["linkers"]),"physical Cargo/Apple ld")
    # Bind raw kernel path spellings to the actual SDK and Xcode on this host for offline replay.
    images={}
    cargo_file=sdk/"bin/cargo"; rustc_file=sdk/"bin/rustc"
    for r in ev:
        spelling=r["path"]
        if spelling in images:continue
        p=Path(spelling)
        if not p.is_file():continue
        if p.samefile(cargo_file):role_key="cargo"
        elif p.samefile(rustc_file):role_key="rustc"
        elif any(l["name"]==p.name and l["sha"]==sha(p) for l in nd["linkers"]):role_key="ld"
        else:continue
        stat=p.stat();images[spelling]={"role":role_key,"resolved":str(p.resolve()),"dev":stat.st_dev,
                                        "ino":stat.st_ino,"sha256":sha(p),"cdhash":r.get("cdhash")}
    save(out/"images.json",images)
    hits=native_outputs(nd,selected)
    marker=emit_markers(units,work,root/"receipts"/"markers",role)
    dirty=[(u["package_id"],u["target"]["name"],u["target"]["kind"]) for u in units if not u["fresh"]]
    native={"typed":len(units),"fresh":len(units)-len(dirty),"dirty":dirty,"full":nd["full"],"link_only":nd["link_only"],
             "stock_ld":sum(ld_output(l["argv"]) is not None for l in nd["linkers"]),
            "stock_ld_queries":sum(ld_output(l["argv"]) is None for l in nd["linkers"]),"terminals":sorted(hits),"real_link_driver":len(nd["cargo_link_driver"])}
    save(out/"native.json",native);save(out/"markers.json",marker)
    proofs={}
    for target,public in selected.items():
        products=out/target;products.mkdir()
        key=keep_image(root/"receipts",public)
        if target in hits:
            p,argv=hits[target]
            # Check only our own output path. The frozen helper also supports a different
            # cross-namespace study, whose rewriting of dependency paths does not apply here.
            held=products/"same-path-recipe";held.mkdir()
            proof=bind_same_path(cgu_inputs.witness(root,held,public.read_bytes(),str(p)),p,argv)
            save(products/"cgu-proof.json",proof)
            need(proof["raw"]==key,"saved Mach-O is not the observed linker result")
            prior[(target,key)]=proof
        else:
            need((target,key) in prior,("reused native body has no matching observed link in this history",target))
            proof=prior[target,key];save(products/"original-link.json",{"raw":key,"recipe":proof["recipe"],"linker_argv":proof["linker_argv"]})
        proofs[target]={k:proof[k] for k in ("raw","output","same_path_image","modules")}
    if name.startswith("empty-") or name=="cold-A" or name=="edit-B":
        need(set(hits)==set(NAMES),("missing genuine executable relink on source transition",name,sorted(hits)))
    row={"revision":rev,"native":native,"cli":check_cli(selected["ruff"],out,rev,env),
         "tests":inventory(selected["integration_test"],selected["ruff"],out,rev,repo,env),"proofs":proofs}
    save(out/"verified.json",row)
    return row

def clear_outputs(work):
    need((work/".owned-empty-stores").read_bytes()==b"rc22-ruff-integration\n","unowned data")
    for n in ("target","shared"):
        p=work/n
        if p.exists():
            need(p.is_dir() and not p.is_symlink() and p.resolve().parent==work,"unsafe local store")
            shutil.rmtree(p)

def compare(row, ref):
    need(row["revision"]==ref["revision"] and row["cli"]==ref["cli"] and row["tests"]==ref["tests"],"nonmatching runtime/complete inventory")
    comparisons={}
    for k,p in row["proofs"].items():
        q=ref["proofs"][k]
        comparisons[k]={"raw_equal":p["raw"]==q["raw"],"same_path":p["output"]==q["output"],
                        "all_signed_bytes_equal_after_verified_object_nonce":p["same_path_image"]==q["same_path_image"],
                        "identical_root_objects":p["modules"]==q["modules"]}
    return comparisons

def hashes_by_revision(rows, refs):
    checks={n:compare(row,refs[row["revision"]]) for n,row in rows.items()}
    for n,check in checks.items():
        for k,v in check.items():
            need(v["same_path"] and v["all_signed_bytes_equal_after_verified_object_nonce"] and v["identical_root_objects"],
                 ("independent same-path native images or objects differ",n,k,v))
    need(set(refs[NEW]["tests"])-set(refs[OLD]["tests"])=={ADDED} and not(set(refs[OLD]["tests"])-set(refs[NEW]["tests"])),
         "unexpected historical integration-test inventory change")
    need(all(refs[OLD]["proofs"][n]["raw"]!=refs[NEW]["proofs"][n]["raw"] for n in NAMES),"missing real native edit")
    return checks

def calibrate(root, trace, env, active_linker):
    out=root/"receipts/calibration";out.mkdir()
    src=out/"probe.c";exe=out/"probe";src.write_text("int main(void){return 13;}\n")
    clang=Path(subprocess.check_output(["xcrun","--find","clang"],text=True).strip())
    apple_sdk=Path(subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],text=True).strip()).resolve(strict=True)
    developer,=[p for p in active_linker.parents if p.name=="Developer" and p.parent.name=="Contents"]
    stub=apple_sdk/"usr/lib/libSystem.tbd"
    need(apple_sdk.is_relative_to(developer/"Platforms/MacOSX.platform/Developer/SDKs") and
         clang.resolve().is_relative_to(developer) and stub.is_file(),"stock Xcode calibration SDK")
    for label,argv,want in [("positive",[str(clang),"-isysroot",str(apple_sdk),str(src),"-o",str(exe)],1),("negative",["/usr/bin/true"],0)]:
        rows=[]
        with (out/(label+".out")).open("xb") as oo,(out/(label+".err")).open("xb") as ee:
            try: status,_=trace.command(argv,cwd=out,env=env,out=oo,err=ee,observed_rows=rows,timeout=50)
            finally: packed(out/(label+"-events.json.gz"),json.dumps(rows).encode())
        hits=[r for r in rows if Path(r["path"]).exists() and Path(r["path"]).samefile(active_linker)]
        need(status==0 and len(hits)==want, "uncalibrated Xcode exec observer "+label)
        if hits:
            pairs=list(zip(hits[0]["argv"],hits[0]["argv"][1:]))
            need([Path(p).resolve() for a,p in pairs if a=="-o"]==[exe.resolve()] and
                 [Path(p).resolve() for a,p in pairs if a=="-syslibroot"]==[apple_sdk],"unbound Xcode calibration output or SDK")
    need(run([exe],cwd=out,env=env).returncode==13,"native sentinel executable changed")
    save(out/"complete.json",{"linker":str(active_linker),"sha256":sha(active_linker),"sdk":str(apple_sdk),
                              "system_stub_sha256":sha(stub),"positive":1,"negative":0,"program_exit":13})

def main(root, bundle):
    root=root.resolve(); ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    need(root.parent==Path(os.environ["RUNNER_TEMP"]).resolve() and not root.exists(),"new private state required")
    root.mkdir(); (root/"receipts/markers").mkdir(parents=True)
    sys.path.insert(0,str(ws/"protocol/scripts/rc22-native"))
    import common, sdk, campaign, plain, observe
    need(common.host()==common.APPLE and shutil.disk_usage(root).free>=28*1024**3,"Apple hardware with 28 GiB entry")
    expected=common.read(ws/"protocol/scripts/rc22-native/source/sdk-apple.json")
    need(common.git(ws/"protocol","rev-parse","HEAD")==os.environ["GITHUB_SHA"] and
         common.git(ws/"protocol","rev-parse","HEAD:scripts/rc22-native")=="784d42db3f6f633a899219406265027cb537ab95" and
         sha(bundle/"receipt.json")==expected["receipt"] and sha(bundle/"members.json")==expected["members"] and sha(bundle/"kit.tar.zst")==expected["kit"],"source-bound protocol/kit")
    kit=root/"kit";receipt=sdk.reopen(bundle,kit); active=kit/"sdk"; work=root/"work";work.mkdir()
    (work/".owned-empty-stores").write_bytes(b"rc22-ruff-integration\n")
    env=common.context(work,active);env.update(CARGO_NET_OFFLINE="true",CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",TZ="UTC")
    repo=ws/"ruff"; need(git(repo,"rev-parse","HEAD").decode().strip()==NEW and git(repo,"rev-parse",NEW+"^").decode().strip()==OLD,"unexpected Ruff pair")
    need(lockset(repo,OLD)==lockset(repo,NEW),"different registry package resolution")
    git(repo,"switch","--detach",OLD); trees(repo,OLD)
    allowed=lockset(repo,OLD)
    fetch={k:v for k,v in env.items() if k!="CARGO_NET_OFFLINE"}
    subprocess.run(["cargo","+ohm","fetch","--locked","--target",common.APPLE],env=fetch,cwd=repo,check=True,timeout=1200)
    packages={p.name:sha(p) for p in (work/"registry/registry/cache").glob("*/*.crate")}
    need(packages and all(allowed.get(n)==h for n,h in packages.items()) and
         all(packages.get(f"{n}-{v}.crate")==h for n,(v,h) in common.LOCKED.items() if n=="zmij"), "unverified locked registry")
    save(root/"receipts/registry.json",packages)
    observe.import_helpers()
    from execs import ExecTrace
    linker=plain.current_linker(kit,receipt)
    fixed={str(p):common.ident(p) for p in (active/"bin/rustc",kit/receipt["rust"]["driver_path"])}
    save(root/"receipts/enrollment.json",{"host":common.host(),"qa":common.job(),"source":expected,"rust":receipt["rust"]["commit"],
         "cargos":receipt["cargos"],"linker":linker,"fixed":fixed,"trees":TREES,"locks":LOCKS,"command":CLI,
         "scope":"one unscored historical Ruff CLI plus integration-test graph; the 391-unit command was not published",
         "environment":{k:v for k,v in env.items()}})
    finished={};refusals={}
    trace=ExecTrace()
    try:
        trace.ready()
        calibrate(root,trace,env,Path(linker["image"]["path"]))
        for role in ("pinned","fourfix"):
            installed=campaign.switch(kit,role,active,receipt)
            need(common.run(["cargo","+ohm","-Vv"],env=env)==receipt["cargos"][role]["version_verbose"],"active Cargo version")
            save(root/"receipts"/role/"selector.json",installed)
            answers={};refs={}
            for history, steps in (("visits",STEPS),("clean-A",(("empty-A",OLD),)),("clean-B",(("empty-B",NEW),))):
                clear_outputs(work); prior={};previous=None
                for name,rev in steps:
                    if rev!=previous:trees(repo,rev)
                    previous=rev
                    row=phase(root,repo,work,active,env,role,name,rev,trace,prior)
                    need(git(repo,"diff","--name-only")==b"" and git(repo,"write-tree").decode().strip()==TREES[rev],"source changed during ordinary build")
                    if history=="visits":answers[name]=row
                    else:refs[rev]=row
                    print(role,name,row["native"]["typed"],row["native"]["fresh"],len(row["native"]["full"]),len(row["native"]["link_only"]),row["native"]["terminals"],flush=True)
            checks={n:compare(v,refs[v["revision"]]) for n,v in answers.items()}
            save(root/"receipts"/role/"clean-comparisons.json",checks)
            try:hashes_by_revision(answers,refs)
            except RuntimeError as error:
                refusals[role]=str(error);save(root/"receipts"/role/"clean-refusal.json",{"error":str(error)})
            need(all(common.ident(Path(p))==i for p,i in fixed.items()),"compiler or driver changed")
            finished[role]={"visits":{n:v["native"] for n,v in answers.items()},"refs":refs}
            clear_outputs(work)
    finally:
        trace.close()
    for rev in (OLD,NEW):
        p=finished["pinned"]["refs"][rev];f=finished["fourfix"]["refs"][rev]
        need((p["cli"],p["tests"])==(f["cli"],f["tests"]),"cross-reader behavior/inventory differs")
    cross={p:{k:compare(finished["pinned"]["refs"][p],finished["fourfix"]["refs"][p])[k] for k in NAMES} for p in (OLD,NEW)}
    need(not refusals,("independent clean equivalence",refusals))
    save(root/"receipts/complete.json",{"native":{r:v["visits"] for r,v in finished.items()},"cross_reader":cross,
                                        "clean_controls":"each revision independently empty for each Cargo at identical paths",
                                        "scored":False})
if __name__=="__main__":
    main(Path(sys.argv[1]),Path(sys.argv[2]))
