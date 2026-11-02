"""Use the exact earlier release/API verifier, and its original installer loop for each enrolled role."""
import datetime, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path
H=Path(__file__).resolve().parent
CFG=json.loads((H/'case.json').read_bytes())
read=lambda path:json.loads(path.read_bytes())
def sha(p):
    with p.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()
def save(path,v):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(v,sort_keys=True,indent=2)+"\n")
def check(v,msg):
    if not v:raise ValueError(msg)
def scope():
    check(__debug__ and os.environ["GITHUB_REPOSITORY"]==CFG["repo"] and os.environ["GITHUB_EVENT_NAME"]=="workflow_dispatch" and os.environ["GITHUB_REF"]=="refs/heads/"+CFG["branch"] and os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"] and os.environ["GITHUB_RUN_ATTEMPT"]=="1","wrong repository/branch/reviewed head/attempt")
    check(datetime.datetime.now(datetime.timezone.utc)<datetime.datetime.fromisoformat(P["dispatch_deadline_utc"]),"original release artifact authority has expired")
def workspace():return Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
def previous():
    w=workspace()/"previous"
    check(subprocess.check_output(["git","-C",w,"rev-parse","HEAD"],text=True).strip()==CFG["coordinator"],"wrong original SDK verifier checkout")
    root=w/"scripts/uv-resolver-whole-pmu"
    check(all(sha(root/k)==v for k,v in CFG["old_files"].items()),"original SDK verification source changed")
    spec=importlib.util.spec_from_file_location("previous_signed_f129",root/"intake.py");mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod
def configure():
    global ORIGINAL,P
    ORIGINAL=previous();P=ORIGINAL.P;scope()
def acquire(out,media):
    configure();media.mkdir();ORIGINAL.released(media,out);ORIGINAL.rebased_input(media,out)
def core_receipt(p):return [p.stat().st_size,sha(p)]
def one(arm,archive_path,pin,installed,out):
    archive = archive_path
    check(sha(archive) == pin, f"{arm} distribution changed")
    sdk = installed / ("sdk-" + arm)
    with tempfile.TemporaryDirectory(prefix="install-", dir=installed) as tmp:
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        dist = Path(tmp) / ("rust-1.99.0-dev-" + P["target"])
        check(list(Path(tmp).iterdir()) == [dist], "unexpected distribution root")
        components = ["rustc", "cargo", "rust-std-" + P["target"]]
        subprocess.run([dist / "install.sh", "--prefix=" + str(sdk), "--disable-ldconfig",
                        "--components=" + ",".join(components)], check=True, timeout=360)
        inventories = {}
        for component in components:
            component_root = dist / component
            lines = (component_root / "manifest.in").read_text().splitlines()
            check(lines and all(line.startswith("file:") for line in lines), "unknown distribution manifest item")
            members = [line[5:] for line in lines]
            check(len(set(members)) == len(members) and
                  set(members) == {f.relative_to(component_root).as_posix() for f in component_root.rglob("*")
                                   if f.is_file() and f != component_root / "manifest.in"}, "incomplete distribution manifest")
            for name in members:
                src, dst = component_root / name, sdk / name
                check(name not in inventories and src.resolve().is_relative_to(component_root) and
                      dst.resolve().is_relative_to(sdk) and not src.is_symlink() and not dst.is_symlink(),
                      "duplicate or external component")
                original = core_receipt(src)
                check(core_receipt(dst) == original, (arm, "installer bytes", name))
                inventories[name] = original
    check(all(inventories.get(k) == v for k, v in P["role_core"][arm].items()), f"{arm} component hashes differ from registered inputs")
    actual = {}
    for command in ("rustc", "cargo"):
        actual[command] = subprocess.check_output([sdk / "bin" / command, "-Vv"], text=True)
        revision = P["role_rust"][arm] if command == "rustc" else P["role_cargo"][arm]
        check("commit-hash: " + revision in actual[command] and "host: " + P["target"] in actual[command], "SDK banner")
    check(Path(subprocess.check_output([sdk / "bin/rustc", "--print", "sysroot"], text=True).strip()).resolve() == sdk, "wrong SDK sysroot")
    ldd = subprocess.check_output(["ldd", sdk / "bin/rustc"], text=True)
    loaded = {}
    for kind in ("librustc_driver", "libLLVM"):
        matches = [Path(p).resolve(strict=True) for n,p in re.findall(r"^\s*(\S+) => (\S+)", ldd, re.M) if n.startswith(kind)]
        check(len(matches) == 1 and matches[0].is_relative_to(sdk), f"wrong loaded {kind}")
        rel = matches[0].relative_to(sdk).as_posix()
        check(inventories[rel] == core_receipt(matches[0]), "loader picked different bytes")
        loaded[kind] = rel
    sections = subprocess.check_output(["readelf", "-SW", sdk / loaded["librustc_driver"]], text=True)
    check(".note.bolt_info" in sections, f"{arm} driver lacks BOLT section")
    summary = {"labels":P["labels"][arm], "sdk":str(sdk), "rust":P["role_rust"][arm], "cargo":P["role_cargo"][arm],
                      "archive_sha256":pin, "loaded":loaded, "banner":actual, "bolt":True}
    save(out / f"installed-{arm}-components.json", inventories)
    evidence=CFG["sdk"][arm]
    check(len(inventories)==evidence["members"]==142 and sha(out/f"installed-{arm}-components.json")==evidence["inventory_sha256"],"installed 142-member inventory differs from the authenticated hosted run")
    save(out/f"verified-{arm}.json",summary)
    return sdk
def install(out,media,installed):
    configure();installed.mkdir()
    signed,=(media/"signed").glob("*.tar.gz");last=P["final"];name=last["name"]+".tar.gz"
    return {"signed":one("signed",signed,P["signed"]["assets"][signed.name]["digest"][7:],installed,out),
            "rebased":one("rebased",media/"rebased"/name,last["pkg_files"][name]["sha256"],installed,out)}
