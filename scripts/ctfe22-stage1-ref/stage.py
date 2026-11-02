"""Build and test the exact materialized source on a fresh hosted stage1 runner."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import probe

H=Path(__file__).resolve().parent;g=probe.g;S=g.load(H/"arms.json");BASE="fa7a_stack_ctfe318";CAND=BASE+"_incoherent_ref"
BRANCH="charlie/codex-ctfe22-sharedref-stage1-probe"; HOST="x86_64-unknown-linux-gnu";UNIT="only_the_original_ctfe_literal_id_is_restored"
NATIVE=S["fixture_directory"];QUERY=S["arms"][CAND]["query_fixture"];REG="tests/run-make/"
def context():
    e=os.environ
    assert e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and e["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and e["GITHUB_REF"]=="refs/heads/"+BRANCH
    assert e["REVIEWED_HEAD"]==e["GITHUB_SHA"] and re.fullmatch("[0-9a-f]{40}",e["GITHUB_SHA"])
    assert e["GITHUB_WORKFLOW_REF"]==e["GITHUB_REPOSITORY"]+"/.github/workflows/ci.yml@"+e["GITHUB_REF"]
    return {k:e[k] for k in ("GITHUB_REPOSITORY","GITHUB_SHA","GITHUB_REF","GITHUB_WORKFLOW_REF","GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT")}
def file_map():
    p=H/"files.json";record=g.load(p)
    assert set(record)=={v.name for v in H.iterdir() if v.is_file() and v!=p}
    assert all(g.file_hash(H/k)==v for k,v in record.items());return g.file_hash(p)
def config(path):
    return '[build]\nbuild-dir = '+json.dumps(str(path))+'\nsubmodules = false\ncompiler-docs = false\n[llvm]\ndownload-ci-llvm = true\n[rust]\nchannel = "dev"\nomit-git-hash = false\ndownload-rustc = false\nlto = "off"\noptimize = true\ndebug-assertions = false\nverbose-tests = true\n'
def verified_version(vv, commit):
    lines = vv.splitlines()
    assert re.fullmatch("[0-9a-f]{40}", commit)
    def field(key):
        value, = [line[len(key)+2:] for line in lines if line.startswith(key + ": ")]
        return value
    assert field("binary") == "rustc" and field("host") == HOST
    assert field("release") == "1.99.0-dev" and field("commit-hash") == commit
    date = field("commit-date")
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date)
    fields = lines[0].split()
    assert len(fields) >= 4 and fields[:2] == ["rustc", "1.99.0-dev"] and fields[3] == date+")"
    short = fields[2].removeprefix("(")
    assert fields[2] == "("+short and 9 <= len(short) <= 40 and commit.startswith(short)
    return lines[0].removeprefix("rustc ")
def suites(role):
    assert role in (BASE,CAND)
    return [NATIVE,REG+"rdr-public-hash-native-exports",REG+"trait-impl-bucket-projection"]+([QUERY] if role==CAND else [])
def passed(raw,which,role):
    text=raw.decode(errors="replace");assert "test result: FAILED" not in text and re.search(r"(?m)^test result: ok\. [1-9]\d* passed; 0 failed; 0 ignored;",text)
    expected=["test mir::interpret::tests::"+UNIT+" ... ok"] if which=="unit" else ["test [run-make] "+test+" ... ok" for test in suites(role)]
    assert all(text.splitlines().count(x)==1 for x in expected)
def match_source(v,role,ctx):
    arm=S["arms"][role]
    assert v["role"]==role and v["source"]==arm and v["released_coordinator"]==S["released_coordinator"] and v["signed_manifest_sha256"]==S["signed_manifest_sha256"] and v["source_pack_sha256"]==S["pack_sha256"]
    assert v["reviewed_head"]==ctx["GITHUB_SHA"] and str(v["run_id"])==ctx["GITHUB_RUN_ID"] and str(v["run_attempt"])==ctx["GITHUB_RUN_ATTEMPT"] and v["workflow_ref"]==ctx["GITHUB_WORKFLOW_REF"] and v["evidence_repository"]==ctx["GITHUB_REPOSITORY"]
    assert v["classification"]=="private stage1-only getter characterization"
def git(repo,*args):return subprocess.check_output(["git","-C",repo,*args],text=True).strip()
def run(role):
    assert __debug__ and role in (BASE,CAND);ctx=context();bundle=file_map()
    w=Path(os.environ["GITHUB_WORKSPACE"]).resolve();r=w/"source/rust";out=w/"trait-evidence";build=w/"stage1-ref-build"
    assert git(w,"rev-parse","HEAD")==ctx["GITHUB_SHA"] and not build.exists() and not (out/"role.json").exists()
    src=g.load(out/"source.json");match_source(src,role,ctx);arm=S["arms"][role]
    assert git(r,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[arm["commit"],arm["tree"]]
    assert not git(r,"diff","--name-only","HEAD","--","compiler","tests","src/bootstrap","src/stage0")
    assert shutil.disk_usage(w).free>=50*(1<<30) and len(os.sched_getaffinity(0))>=8
    cfg=out/"bootstrap.toml";cfg.write_text(config(build));env={k:os.environ[k] for k in ("PATH","HOME","SSL_CERT_FILE","CARGO_HOME","RUSTUP_HOME") if os.environ.get(k)}|{"LC_ALL":"C","PYTHONDONTWRITEBYTECODE":"1"}
    opts=[sys.executable,str(r/"x.py"),"--ci","false","--config",str(cfg)]
    flags=["--stage","1","-j8","--host",HOST,"--target",HOST]
    cmds={"build":opts+["build",*flags,"compiler/rustc","library"],"unit":opts+["test",*flags,"compiler/rustc_middle","--test-args",UNIT],"run-make":opts+["test",*flags,*suites(role)]}
    g.put(out/"commands.json",cmds)
    for key,cmd in cmds.items():
        log=out/(key+".log")
        with log.open("xb") as f:subprocess.run(cmd,cwd=r,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        assert log.stat().st_size<32<<20
        if key!="build":passed(log.read_bytes(),key,role)
    sdk=build/HOST/"stage1";senv={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(sdk/"lib")}
    ident=g.sdk_identity(sdk,senv,arm["commit"],None);vv=ident["rustc_vV"]
    (out/"rustc-vV.txt").write_bytes(vv.encode())
    version=verified_version(vv, arm["commit"])
    libs=subprocess.check_output(["ldd",sdk/"bin/rustc"],env=senv,text=True);assert "not found" not in libs
    driver,=[name.split(" => ",1)[1].split()[0] for name in libs.splitlines() if name.lstrip().startswith(ident["driver"]+" => ")]
    assert Path(driver).samefile(sdk/"lib"/ident["driver"]) and g.file_hash(Path(driver))==ident["driver_sha256"]
    ident["resolved_llvm"]={v[0]:g.file_hash(Path(v[1])) for v in re.findall(r"(?m)^\s*(libLLVM\S+) => (\S+)",libs)}
    stage0=build/HOST/"stage0/bin";ident["stage0"]={n:g.file_hash(stage0/n) for n in ("rustc","cargo")}
    ident["bootstrap_objects"]={p:git(r,"rev-parse","HEAD:"+p) for p in ("src/stage0","src/bootstrap","src/llvm-project","compiler/rustc_span/src/def_id.rs")}
    g.put(out/"identity.json",ident)
    root=out/"observed";root.mkdir();counts=probe.run(sdk,version.encode(),root)
    with tempfile.TemporaryDirectory(prefix="ohm-method-states-v1-") as t:
        methods=g.bucket_states(sdk,Path(t)/"live",senv,g.load(H/"methods.json"))
    assert [row["stdout"] for row in methods]==["0 0","13 0","13 0","13 29","0 29","0 0","13 0"]
    assert len({method["stdout"] for method in methods})==4
    g.put(out/"methods.json",methods)
    assert not git(r,"diff","--name-only","HEAD","--","compiler","tests","src/bootstrap","src/stage0")
    files={f.relative_to(out).as_posix():g.file_hash(f) for f in sorted(out.rglob("*")) if f.is_file()}
    g.put(out/"role.json",{"schema":1,"role":role,"context":ctx,"files_manifest":bundle,"role_source":arm,"observed":counts,"files":files})
    capsule=w/"qualified-role.zip";assert not capsule.exists()
    with zipfile.ZipFile(capsule,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for name in [*files,"role.json"]:z.write(out/name,name)
    assert capsule.stat().st_size<96<<20
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as f:print("inner="+g.file_hash(capsule),file=f)
if __name__=="__main__":run(*sys.argv[1:])
