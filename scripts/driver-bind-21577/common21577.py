from pathlib import Path
import gzip, hashlib, json, os, re, runpy, shutil, subprocess, sys, tempfile, tomllib
HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent / "uv-check-21134"
sys.path.insert(0, str(LEGACY))
import common as h
ROOT, SRC, TARGET, SDK = h.ROOT, h.SRC, h.TARGET, h.SDK
save, read, need, sha, blob = h.save, h.read, h.require, h.sha, h.blob
PLAN = read(HERE / "protocol.json")
CASE = read(HERE / "case.json")
WORK = PLAN["workload"]
CHECK = WORK["cargo"]
h.CHECK = CHECK
ENV = h.ENV
assert ENV == read(HERE / "environment.json")
NAMES = set(WORK["roster"])
def normalized_surface():
    files = {str(f.relative_to(TARGET)): blob(f) for f in sorted(TARGET.rglob("*.rmeta"))}
    typed, relative = h.normalized(files)
    side = {str(f.relative_to(TARGET)): blob(f) for f in sorted(TARGET.rglob("*.public-api-hash"))}
    local = {tomllib.loads(t.read_text())["package"]["name"].replace("-", "_") for t in (SRC/"crates").glob("*/Cargo.toml")}
    workspace = {k:v for k,v in files.items() if Path(k).name[3:].split("-")[0] in local}
    assert len(typed) == 39 and len(side) == 30 and len(workspace) == 4
    return {"rmeta":typed, "sidecars":side, "workspace":workspace}, relative
def surface(dst, store):
    doc, rel = normalized_surface()
    save(dst/"products.json", doc)
    save(dst/"literal-rmeta-paths.json", rel)
    for name, fp in doc["rmeta"].items():
        f = TARGET / rel[name]
        if not (store / (fp[1]+".gz")).is_file():
            assert h.retain(f, store) == fp
    for name, fp in doc["sidecars"].items():
        dest = store / (fp[1]+".public-api-hash")
        if not dest.exists(): shutil.copyfile(TARGET/name, dest)
        assert blob(dest) == fp
    return doc
def source(d, phase, donor=None):
    a,b = WORK["A"],WORK["B"]
    wanted = read(HERE/("source-"+phase+".json"))
    if donor is not None:
        assert not d.exists()
        d.mkdir()
        h.git(d,"init","-q")
        h.git(d,"fetch","--no-tags","--depth=20",donor.resolve().as_uri(),b)
        h.git(d,"checkout","-q","--detach",a)
        assert h.git(d,"cat-file","-t",WORK["tag"]).strip()==b"commit"
        h.git(d,"update-ref","refs/tags/"+WORK["tag_name"],WORK["tag"])
        h.git(d,"config","--local","core.abbrev","8")
    assert h.git(d,"rev-parse","HEAD").decode().strip()==a
    assert h.git(d,"rev-parse",b+"^").decode().strip()==a
    assert h.git(d,"rev-parse","refs/tags/"+WORK["tag_name"]).decode().strip()==WORK["tag"]
    assert h.git(d,"describe","--long","--tags").decode().strip()==WORK["tag_describe"]
    assert not h.git(d,"diff","--cached","--name-only") and not h.git(d,"ls-files","--others","--exclude-standard")
    for name,new in wanted["files"].items():
        old = sha(d/name)
        assert old in [read(HERE/("source-"+s+".json"))["files"][name] for s in "AB"]
        if old != new: (d/name).write_bytes(h.git(d,"show",{"A":a,"B":b}[phase]+":"+name))
        assert sha(d/name)==new
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        e=dict(ENV,GIT_INDEX_FILE=str(Path(tmp)/"checked.index")); h.git(d,"read-tree",a,env=e); h.git(d,"add","-u","--",env=e);tree=h.git(d,"write-tree",env=e).decode().strip()
    assert tree==wanted["actual_tree"] and sha(d/"Cargo.lock")==wanted["lock"]
    changes=h.git(d,"diff","--name-only").decode().splitlines()
    assert set(changes)==(set(wanted["files"]) if phase=="B" else set())
    return {"phase":phase,"working_tree":tree,"branch_index_head":a,"files":wanted["files"],"lock":wanted["lock"],"real_tag":WORK["tag"],"describe":WORK["tag_describe"]}
def registry():
    enrolled=read(HERE/"registry.json")["packages"]
    cache=Path(ENV["CARGO_HOME"])/"registry/cache"; dirs=list(cache.iterdir()); assert len(dirs)==1
    registry=dirs[0];idx=cache.parent/"index"/registry.name
    cfg=read(idx/"config.json");explicit_original=sha(idx/"config.json")=="b53c1616e30600e72868bee2d214fd7a5495759368db642698f2af5f38f714d6"
    assert explicit_original or (cfg.get("api")=="https://crates.io" and cfg.get("dl") in("https://static.crates.io/crates","https://static.crates.io/crates/{crate}/{crate}-{version}.crate"))
    for filename,r in enrolled.items():
        assert blob(registry/filename)==[r["size"],r["sha256"]]
        n=r["name"].lower();directory={1:"1",2:"2",3:"3/"+n[0]}.get(len(n),n[:2]+"/"+n[2:4])
        data=(idx/".cache"/directory/n).read_bytes();assert data[:1]==b"\x03" and data[-1:]==b"\0"
        parts=data[5:-1].split(b"\0");line,=[raw for ver,raw in zip(parts[1::2],parts[2::2]) if ver==r["version"].encode()]
        row=json.loads(line)
        assert row["name"]==r["name"] and row["cksum"]==r["sha256"] and h.canonical(row)==r["full_json_sha256"]
    assert len(enrolled)==682
    return {"registry_cache":registry.name,"all_archives_checked":len(enrolled),"manifest_sha256":sha(HERE/"registry.json"),"config_sha256":sha(idx/"config.json")}
def behavior(role,out,donor):
    dst=ROOT/("linked-"+role);dst.mkdir();pkg=dst/"case";(pkg/"src").mkdir(parents=True);out.mkdir()
    env=dict(ENV,CARGO_TARGET_DIR=str(dst/"target"),CARGO_PROFILE_DEV_DEBUG="0",CARGO_PROFILE_DEV_INCREMENTAL="false")
    result={}
    for phase in "AB":
        u=dst/"uv";original=source(u,phase,donor if phase=="A" else None)
        f=out/phase;f.mkdir();shutil.copyfile(HERE/("behavior-"+phase+".rs"),pkg/"src/main.rs")
        (pkg/"Cargo.toml").write_text('[package]\nname="warning-order-witness"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nuv-errors={path="../uv/crates/uv-errors"}\nuv-warnings={path="../uv/crates/uv-warnings"}\n')
        shutil.copyfile(u/"Cargo.lock",pkg/"Cargo.lock")
        def entries(p):
            return {(r["name"],r["version"],r.get("source"),r.get("checksum")) for r in tomllib.loads(p.read_text())["package"]}
        original_lock=entries(u/"Cargo.lock")
        h.invoke([h.CARGO,"metadata","--offline","--format-version=1"],pkg,env,stdout=subprocess.DEVNULL)
        actual={x for x in entries(pkg/"Cargo.lock") if x[0]!="warning-order-witness"};assert len(actual)==53 and actual<=original_lock
        with (f/"compiler.stdout").open("xb")as stdout,(f/"compiler.stderr").open("xb")as stderr:
            h.invoke([h.CARGO,"build","--locked","--offline","-j4","--message-format=json"],pkg,env,stdout=stdout,stderr=stderr)
        events=[json.loads(line) for line in (f/"compiler.stdout").read_bytes().splitlines() if line.startswith(b"{")]
        exe,=[Path(r["executable"]) for r in events if r.get("target",{}).get("name")=="warning-order-witness"]
        inputs={r["target"]["name"]:[(s,blob(Path(s))) for s in r["filenames"] if s.endswith(".rlib")] for r in events if r.get("target",{}).get("name") in NAMES}
        assert set(inputs)==NAMES and all(len(v)==1 for v in inputs.values())
        run=h.invoke([exe],pkg,env,capture_output=True);(f/"stdout").write_bytes(run.stdout);(f/"stderr").write_bytes(run.stderr)
        message=run.stderr;assert not run.stdout and all(message.count(t)==1 for t in (b"original warning",b"general-last",b"specific-first"))
        assert (message.index(b"general-last")<message.index(b"specific-first"))==(phase=="A")
        result[phase]={"output":message.decode(),"linked":inputs,"source":original,"test":sha(pkg/"src/main.rs"),"exe":sha(exe),"lock":sha(pkg/"Cargo.lock")}
    save(out/"passed.json",result);shutil.rmtree(dst);return result
