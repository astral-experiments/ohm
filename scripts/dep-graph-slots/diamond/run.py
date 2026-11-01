"""Run the public and candidate rustdoc on a cold and a build-trained real Ruff diamond."""
import gzip
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inputs import BIND, digest, need, registry, write_source

COLLISION = "found crates (`ruff_text_size` and `ruff_text_size`) with colliding StableCrateId values"


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def record(folder, argv, src, env):
    folder.mkdir()
    save(folder / "invocation.json", {"argv":list(map(str,argv)), "cwd":str(src), "env": env})
    proc = subprocess.run(argv, cwd=src, env=env, capture_output=True, timeout=150)
    for stream in ("stdout","stderr"):
        (folder / (stream+".gz")).write_bytes(gzip.compress(getattr(proc,stream),mtime=0))
    save(folder / "exit.json", proc.returncode)
    return proc


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words=[]
        self.links=[]

    def handle_data(self, text):
        self.words.append(text)

    def handle_starttag(self, tag, attrs):
        if tag=="a":
            self.links.extend(v for k,v in attrs if k=="href" and v is not None)


def pages(target, out):
    root=target/"doc"/"facade"
    bodies={}
    for name in ("index.html","struct.TextSize.html","fn.line_start.html"):
        data=(root/name).read_bytes()
        need(1024<len(data)<3<<20, "unexpected HTML size")
        parsed=Markup()
        parsed.feed(data.decode())
        words=" ".join(" ".join(parsed.words).split())
        if name=="index.html":
            need(all(any(link.split("#")[0].endswith(n) for link in parsed.links)
                     for n in ("struct.TextSize.html","fn.line_start.html")), "facade lacks links to its items")
        elif name.startswith("struct"):
            need("A measure of text length." in words and "TextSize" in words, "wrong real Ruff documentation")
        else:
            need("Returns the start of the line that contains the given byte offset." in words
                 and "line_start" in words and "TextSize" in words, "wrong nominal crossing documentation")
        bodies[name]=digest(data)
        (out/(name+".gz")).write_bytes(gzip.compress(data,mtime=0))
    return bodies


def versions(sdk, env, expected, folder, src):
    result={}
    for k in ("cargo","rustc","rustdoc"):
        vv=record(folder/(k+"-version"),[k,"+ohm","-vV"],src,env)
        which=record(folder/(k+"-which"),["rustup","which","--toolchain","ohm",k],src,env)
        path=Path(os.fsdecode(which.stdout).strip())
        need(which.returncode==vv.returncode==0 and path.samefile(sdk/"bin"/k), "different physical "+k)
        sha=digest(path.read_bytes())
        want=expected["cargo_commit" if k=="cargo" else "rust_commit"]
        need(sha==expected[k] and ("commit-hash: "+want) in vv.stdout.decode().splitlines(), "different selected "+k)
        result[k]={"path":str(path),"sha256":sha,"version":vv.stdout.decode()}
    return result


def run_role(root, out, sdk, launcher, role, expected, host, cache_id="index.crates.io-1949cf8c6b5b557f"):
    """Fresh starts share an absolute source, target, build and Cargo home within the private root."""
    need(role in {"published-22","corrected","fd98-control"}, "wrong tool role")
    root.mkdir()
    out.mkdir()
    src=root/"project"
    source=write_source(src)
    (root/"rustup/toolchains").mkdir(parents=True)
    (root/"rustup/toolchains/ohm").symlink_to(sdk.resolve(strict=True),target_is_directory=True)
    (root/"rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    (root/"user").mkdir()
    (root/"tmp").mkdir()
    (out/"identity").mkdir()
    env=dict(HOME=str(root/"user"), RUSTUP_HOME=str(root/"rustup"), RUSTUP_AUTO_INSTALL="0",
             PATH=str(launcher)+os.pathsep+os.environ["PATH"], TMPDIR=str(root/"tmp"),
             CARGO_HOME=str(root/"registry"), CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never",
             CARGO_TARGET_DIR=str(root/"target"), CARGO_BUILD_BUILD_DIR=str(root/"build"), LC_ALL="C")
    if host=="aarch64-apple-darwin":
        env["LLVM_PROFILE_FILE"]=str(root/"tmp/diamond-%m.profraw")
        for k in ("SDKROOT","DEVELOPER_DIR","MACOSX_DEPLOYMENT_TARGET"):
            if k in os.environ:
                env[k]=os.environ[k]
    tools=versions(sdk,env,expected,out/"identity",src)
    need(all(("host: "+host) in v["version"].splitlines() for v in tools.values()), "different SDK host")
    save(out/"sources.json",BIND)
    results={}
    for mode in ("default","off"):
        for history in ("cold-doc","build-doc"):
            case=out/(mode+"-"+history)
            case.mkdir()
            rows={}
            for dirname in ("target","build","registry"):
                folder=root/dirname
                if folder.exists():
                    # Only tools can create the isolated initially empty Cargo home during -vV.
                    need(not folder.is_symlink() and not set(folder.iterdir()), "previous build state present")
                    folder.rmdir()
            registry(root/"registry",source["Cargo.lock"],cache_id)
            need(not (root/"target").exists() and not (root/"build").exists(), "nonempty input roots")
            prefix=["cargo","+ohm"]+(["-Zohm-defaults=no"] if mode=="off" else [])
            for op in (["build","doc"] if history=="build-doc" else ["doc"]):
                folder=case/op
                args=prefix+[op,"-p",("facade" if op=="doc" else "client")]+(["--no-deps"] if op=="doc" else [])+["--offline","--locked","-j2","--message-format=json"]
                run=record(folder,args,src,env)
                units=[json.loads(line) for line in run.stdout.splitlines()]
                need(units and units[-1]=={"reason":"build-finished","success":run.returncode==0}, "incomplete Cargo JSON")
                errors=[u["message"]["message"] for u in units if u.get("reason")=="compiler-message" and u["message"]["level"]=="error"]
                typed=[u for u in units if u.get("reason")=="compiler-artifact"]
                products={}
                for u in typed:
                    for filename in u["filenames"]:
                        f=Path(filename)
                        if f.is_file() and f.suffix in {".rmeta",".rlib"}:
                            products[str(f)]={"package":u["package_id"],"sha256":digest(f.read_bytes()),"bytes":f.stat().st_size,"fresh":u["fresh"]}
                item={"status":run.returncode,"errors":errors,"products":products}
                if op=="doc":
                    leaf=[u for u in typed if u["target"]["name"]=="ruff_text_size"]
                    files=sorted(sorted(Path(f).suffix for f in u["filenames"]) for u in leaf)
                    expected_files=([[".rlib",".rmeta"],[".rmeta"]] if mode=="default" and role in ("published-22","fd98-control") else [[".rmeta"]])
                    need(files==expected_files, "unexpected leaf metadata/rlib topology")
                    item["leaf_products"]=[u["filenames"] for u in leaf]
                if op=="build":
                    (client,)=[u["executable"] for u in typed if u["target"]["name"]=="client" and u["executable"]]
                    need(run.returncode==0 and not errors and all(any(u["target"]["name"]==n for u in typed)
                         for n in ("ruff_text_size","ruff_source_file","memchr","facade","client")), "missing genuine Cargo build")
                    native=record(case/"native",[client],src,env)
                    need(native.returncode==0 and native.stdout==b"4 5\n" and not native.stderr, "wrong linked nominal result")
                    data=Path(client).read_bytes();need(0<len(data)<16<<20,"oversized client")
                    (case/"client.gz").write_bytes(gzip.compress(data,mtime=0));item.update(client=digest(data),output=native.stdout.decode())
                elif role in ("published-22","fd98-control") and mode=="default":
                    need(run.returncode==101 and errors==[COLLISION] and not (root/"target/doc/facade/struct.TextSize.html").exists(),"old compiler did not reproduce the exact collision")
                else:
                    need(run.returncode==0 and not errors,"rustdoc failed")
                    item["pages"]=pages(root/"target",folder)
                rows[op]=item
                save(folder/"result.json",item)
            results[case.name]=rows
            for dirname in ("target","build","registry"):
                path=root/dirname
                need(path.parent==root and path.is_dir() and not path.is_symlink(), "foreign temporary output")
                shutil.rmtree(path)
            need(all(digest((src/k).read_bytes())==h for k,h in BIND["source_files"].items()), "source changed")
            save(out/"progress.json",results)
    save(out/"complete.json",{"role":role,"host":host,"tools":tools,"source":BIND["archive"],"cases":results})
    return results
