"""Authenticate the source trees and immutable GitHub donor on a new QA worker."""
import hashlib
import gzip
import json
import os
import tempfile
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = lambda: json.loads((HERE / "roles.json").read_bytes())
HOST = "x86_64-unknown-linux-gnu"
CARGO = "761ea115605c34f11a1cd29afd68812c1e1359dd"
ELF = "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4"
BUILD = "d54bc38a259b60b17168c745fa19389d81f9d861b7be42ef04e09b4de4e8ea4c"
WILD = "lib/rustlib/" + HOST + "/bin/wild-ld/ld.bfd"
WILD_SHA = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
RUN = 41151297839
QA = "f23a67771c625785cd70f58e9b46e8d26af3d317"
REPO = "astral-experiments/ohm"
DONORS = [(13023471212, "disposable-gc-qualified-cargo", 17661123, "9a259bfc8b82d2bbf67d7d45b01c56902e8e4eff7654cc34d1537881868a76c2"),
          (13023271637, "gc-qualified-cargo-build-record", 37080, "c3316118ecb13fd54259b7ae760f9daccb978ee0acd39437404dfcec654a3eff")]


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(repo, *args, data=None, env=None):
    return subprocess.check_output(["git", "-C", repo, *args], input=data, env=env)


def rev(repo, value):
    return git(repo, "rev-parse", value).decode().strip()


def identity_delta(repo, left, right):
    raw=git(repo,"diff-tree","-r","--raw","-z","--no-abbrev","--no-renames",left,right)
    parts=raw.split(b"\0");need(parts.pop()==b"" and len(parts)%2==0,"invalid binary diff-tree")
    rows=[]
    for header, name in zip(parts[::2],parts[1::2],strict=True):
        a,b,old,new,status=header.decode("ascii").split()
        row={"path":name.decode("utf-8"),"change":status}
        for key,mode,oid in (("old",a[1:],old),("new",b,new)):
            if oid=="0"*40:
                need(mode=="000000","missing-side mode")
                row[key]=None
            else:
                data=git(repo,"cat-file","blob",oid)
                need(hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==oid,"invalid Git blob")
                row[key]={"mode":mode,"oid":oid,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
        rows.append(row)
    return {"raw_sha256":hashlib.sha256(raw).hexdigest(),"rows":rows}


def exact_patch(repo, left, right, patch):
    with tempfile.TemporaryDirectory() as d:
        env=dict(os.environ,GIT_INDEX_FILE=str(Path(d)/"index"))
        flags=("-c","core.sparseCheckout=false","-c","core.splitIndex=false")
        git(repo,*flags,"read-tree",left,env=env)
        args=(*flags,"apply","--cached","--binary","--whitespace=nowarn")
        git(repo,*args,"--check","-",data=patch,env=env)
        git(repo,*args,"-",data=patch,env=env)
        actual=git(repo,*flags,"write-tree",env=env).decode().strip()
        need(actual==rev(repo,right+"^{tree}"),"original complete patch did not yield the entire intended tree")
        return actual


def source(repo, install, receipt=None):
    reg = SOURCE()
    if install:
        old = HERE.parent / "ohm-packed-ruff/packed-objects.bundle"
        need(sha(old) == reg["historical_bundle_sha256"], "wrong old source bundle")
        git(repo, "bundle", "verify", old)
        git(repo, "fetch", "--no-tags", "--no-recurse-submodules", old,
            "refs/heads/charlie/compact-inactive-branch-objects")
        need(rev(repo, "FETCH_HEAD") == reg["roles"]["old_packed"]["commit"], "wrong old branch")
        pack = HERE / "role-history.pack"
        need(sha(pack) == reg["pack"]["sha256"] and pack.stat().st_size == reg["pack"]["size"], "wrong live pack")
        git(repo, "index-pack", "--stdin", data=pack.read_bytes())
    for v in reg["roles"].values():
        head = v["commit"]
        for name in ("tree", "compiler", "library", "tests"):
            need(rev(repo, head + ("^{tree}" if name == "tree" else ":"+name)) == v[name], "wrong source "+name)
    full, packed, old_f, old_k = [reg["roles"][k]["commit"] for k in ("F", "K", "old_full", "old_packed")]
    need(rev(repo, packed+"^") == full, "packed is not the exact reviewed child")
    for newer, older in [(full,old_f),(packed,old_k)]:
        need(git(repo,"diff","--name-only",older,newer).decode().splitlines() == reg["live_only"], "old versus live source")
    patch=gzip.decompress((HERE/"original-full-index.patch.gz").read_bytes())
    need(hashlib.sha256(patch).hexdigest()==reg["patch_sha256"],"original historical patch changed")
    expected=json.loads((HERE/"delta.json").read_bytes()); comparisons={}; renders=[]
    for name,l,r in [("live",full,packed),("historical",old_f,old_k)]:
        diff=git(repo,"-c","color.ui=false","diff","--no-ext-diff","--no-textconv","--no-renames","--binary","--full-index",l,r)
        renders.append(diff)
        ids=identity_delta(repo,l,r)
        if receipt:
            (receipt/(name+"-actual-full-index.patch")).write_bytes(diff)
            write(receipt/(name+"-actual-delta.json"),ids)
        need(ids==expected and [x["path"] for x in ids["rows"]]==reg["paths"],"foreign changed mode, object, path or blob content")
        comparisons[name]={"rendered_sha256":hashlib.sha256(diff).hexdigest(),"rendered_size":len(diff),"verified_tree":exact_patch(repo,l,r,patch),"raw_sha256":ids["raw_sha256"]}
    if receipt:
        write(receipt/"source-delta-presentation.json",{"historical_reference":reg["patch_sha256"],"pairs":comparisons,
              "git_version":git(repo,"version").decode().strip(),"attributes":git(repo,"check-attr","--all","--",*reg["paths"]).decode().splitlines()})
    need(renders[0]==renders[1],"different actual runner full-index diffs")
    need(int(git(repo,"rev-list","--count",packed,"^"+old_k)) == reg["traversable_commits"], "truncated history")
    return reg


def api(path):
    return json.loads(subprocess.check_output(["gh","api","repos/"+REPO+"/actions/"+path]))


def cargo(root, receipt):
    root.mkdir()
    run = api(f"runs/{RUN}")
    need((run["id"],run["head_sha"],run["run_attempt"]) == (RUN,QA,1), "wrong source builder run")
    jobs = api(f"runs/{RUN}/attempts/1/jobs")["jobs"]
    job, = [j for j in jobs if j["id"] == 124388202956]
    need((job["name"],job["head_sha"],job["conclusion"]) == ("builder",QA,"success"), "source builder did not pass")
    catalog = api(f"runs/{RUN}/artifacts")["artifacts"]
    receipts = []
    for ident,name,size,digest in DONORS:
        row, = [x for x in catalog if x["id"] == ident]
        need((row["name"],row["size_in_bytes"],row["digest"],row["expired"],row["workflow_run"]["head_sha"]) ==
             (name,size,"sha256:"+digest,False,QA), "wrong authentic native Cargo artifact")
        dest = root / (name+".zip")
        with dest.open("xb") as out:
            subprocess.run(["gh","api",f"repos/{REPO}/actions/artifacts/{ident}/zip"],stdout=out,check=True)
        need(dest.stat().st_size == size and sha(dest)==digest,"official Cargo ZIP checksum")
        with zipfile.ZipFile(dest) as z:
            need(len(z.namelist()) == len(set(z.namelist())) and not z.testzip(), "bad donor archive entry")
            need(hashlib.sha256(z.read("build.json")).hexdigest()==BUILD, "wrong donor source receipt")
            if ident==DONORS[0][0]:
                need(set(z.namelist()) == {"cargo","build.json"}, "unexpected source artifact")
                native=root/"cargo-761"
                native.write_bytes(z.read("cargo"));native.chmod(0o755)
                (receipt/"strict-cargo-build.json").write_bytes(z.read("build.json"))
        receipts.append(dict(id=ident,name=name,bytes=size,sha256=digest))
    data=json.loads((receipt/"strict-cargo-build.json").read_bytes())
    need(data["compiled"]==data["delivered"]==sha(native)==ELF and native.stat().st_size==51101864 and
         data["candidate"]==data["tree"]["commit"]==CARGO and data["qa"]==QA and
         {"ohm-defaults","all-static"}<=set(data["features"]),"native/source Cargo mismatch")
    version=subprocess.check_output([native,"-Vv"],text=True)
    need("commit-hash: "+CARGO in version, "different running Cargo")
    write(receipt/"cargo-origin.json",dict(artifacts=receipts,run=RUN,qa=QA,attempt=1,job=job["id"],version=version))
