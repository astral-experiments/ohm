"""Select a source pass only in the signed rustc child, with physical per-process evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


ARMS = {"signed": [], "stock": [], "strict": []}
LLVM = "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
PATCH = "8df654501c995c2e419a6402c15bed1942df7e423df982448ab0d22cffee051b"
FILES = {"wrapper", "loader.so", *(a+"-"+v for a in ("stock","strict") for v in ("plain","inspect"))}
REGISTERED = {"stock-plain":"692e59901cc2b9f00d4e04d0941df562b159f6d701490855060feda7d6d50947",
              "strict-plain":"074561b2cfaa3b623081b3ce2c701bee34cb40f4d334c1c310b21bf1a19ddf99",
              "stock-inspect":"504ecc0509a438d18e7905571f9fa94a92033a6f3809453414b5e618c818351e",
              "strict-inspect":"c482f99bba95547c37f51966dc45b60fce811742e96355ac1cc18b2feb45c22a"}


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def validate(m, *, host_control=False):
    if not isinstance(m,dict):
        m=json.loads(Path(m).read_bytes())
    schema="ohm-host-source-pass-control-v1" if host_control else "ohm-source-pass-suite-v1"
    need(m["schema"]==schema and m["patch"]==PATCH and m["signed_llvm"]==LLVM
         and set(m["variants"])==FILES, "wrong source pass manifest")
    root=Path(m["root"]).resolve(strict=True)
    need(sha(root/"provenance.json")==m["provenance"],"changed source build provenance")
    proof=json.loads((root/"provenance.json").read_bytes())
    need(proof["patch"]==PATCH and proof["signed_llvm"]==LLVM and proof["headers"]["source"]==234
         and proof["registration"]["archive_sha256"]=="ba42780456b37115ab3f1f9368a8a8294195650155e8d51e409fa5d731b54ea6"
         and len(proof["headers"]["generated"])==5 and proof["llvm"]=="1b9c0d5ff9bbe7634aead059efe6b11a7eeba145",
         "unregistered source build inputs")
    for name, digest in m["variants"].items():
        path=root/(name if name in ("wrapper","loader.so") else name+".so")
        wanted=proof["host_variants" if host_control else "variants"][name]["sha256"]
        need((host_control or name not in REGISTERED or digest==REGISTERED[name]) and digest==wanted
             and path.is_file() and not path.is_symlink() and sha(path)==digest,("changed native input",path))
    return m


def select(m,arm,env,inspected=False):
    need(arm in ARMS and "LD_PRELOAD" not in env and "RUSTC_WRAPPER" not in env
         and "RUSTC_WORKSPACE_WRAPPER" not in env, "unexpected base environment")
    root=Path(m["root"]).resolve(strict=True)
    compiler=Path(m["signed_rustc"]).resolve(strict=True)
    workspace=Path(env["CARGO_TARGET_DIR"]).parent.parent/"ruff"
    slot=workspace.parent/"source-pass"
    need(workspace.is_dir() and not workspace.is_symlink(), "private workspace unavailable")
    if not slot.exists():
        slot.mkdir(mode=0o700)
        (slot/"audit").mkdir(mode=0o700)
        for name in ("wrapper","loader.so"):
            shutil.copy2(root/name,slot/name)
            (slot/name).chmod(0o555)
    for name in ("wrapper","loader.so"):
        need(sha(slot/name)==m["variants"][name],("unverified launcher component",name))
    variant=arm+("-inspect" if inspected else "-plain")
    active=slot/"active.so"
    if arm!="signed":
        source=root/(variant+".so")
        need(sha(source)==m["variants"][variant],("changed native variant",variant))
        (slot/"active.tmp").symlink_to(source)
        os.replace(slot/"active.tmp",active)
        mode="plugin"
    else:
        active.unlink(missing_ok=True)
        mode="signed"
    (slot/"mode.tmp").write_text(mode+"\n")
    os.replace(slot/"mode.tmp",slot/"mode")
    selected={**env,"RUSTC":str(compiler),"RUSTC_WRAPPER":str(slot/"wrapper"),
              "OHM_SOURCE_PASS_RUSTC":str(compiler),"OHM_SOURCE_PASS_WORKSPACE":str(workspace),
              "OHM_SOURCE_PASS_DIR":str(slot),"OHM_SOURCE_PASS_AUDIT":str(slot/"audit")}
    identity={"mode":"signed-source-pass","root":str(root),"signed_rustc":str(compiler),"patch":PATCH,
              "arm":arm,"variant":None if mode=="signed" else variant,"provenance":m["provenance"],
              "sha256":None if mode=="signed" else m["variants"][variant]}
    return selected,[],compiler,identity


def snapshot(env):
    return {p.name for p in Path(env["OHM_SOURCE_PASS_AUDIT"]).iterdir()}


def collect(env,before,arm,inspected):
    folder=Path(env["OHM_SOURCE_PASS_AUDIT"])
    fresh=snapshot(env)-before
    need(all(re.fullmatch(r"[1-9][0-9]*\.(argv|load|pass)",n) for n in fresh), "unrecognized native receipt")
    groups={}
    for name in fresh:
        pid,kind=name.split(".")
        groups.setdefault(pid,{})[kind]=folder/name
    product=[]
    for pid,parts in sorted(groups.items()):
        want={"argv"} if arm=="signed" else ({"argv","load","pass"} if inspected else {"argv","load"})
        need(set(parts)==want,("missing or unexpected physical receipt",pid,parts,want))
        raw=parts["argv"].read_bytes()
        need(raw.endswith(b"\0"),"unterminated native argv")
        event,cwd,wrapper,cc,*argv=[s.decode() for s in raw[:-1].split(b"\0")]
        need(event==("signed" if arm=="signed" else "plugin") and Path(wrapper).samefile(env["RUSTC_WRAPPER"])
             and Path(cc).samefile(env["RUSTC"]),"wrong native compiler child")
        name=argv[argv.index("--crate-name")+1]
        need(name in ("ruff_workspace","ty_server","e2e") and not any("llvm-plugins" in s or "llvm-args" in s for s in argv),
             ("out-of-scope native compiler",name))
        root=Path(env["OHM_SOURCE_PASS_WORKSPACE"])
        rel={"ruff_workspace":"crates/ruff_workspace/src/lib.rs","ty_server":"crates/ty_server/src/lib.rs","e2e":"crates/ty_server/tests/e2e/main.rs"}[name]
        need(sum(s.endswith(".rs") and (Path(cwd)/s).resolve()==root/rel for s in argv)==1,("unexpected native compiler source",name))
        row={"pid":int(pid),"event":event,"owner":name,"cwd":cwd,"argv":argv,"argv_sha256":hashlib.sha256(raw).hexdigest()}
        if "load" in parts:
            lib=(Path(env["OHM_SOURCE_PASS_DIR"])/"active.so").stat()
            need(list(map(int,parts["load"].read_text().split()))==[lib.st_dev,lib.st_ino],"native loader mapped a different module")
            row["load"]=[lib.st_dev,lib.st_ino]
        if "pass" in parts:
            label,*vals=parts["pass"].read_text().split()
            need(label==("candidate" if arm=="strict" else "stock") and len(vals)==4 and all(s.isdecimal() for s in vals),
                 ("unexpected physical pass counters",label,vals))
            row["counts"]=dict(zip(("installed","machines","direct","skips"),map(int,vals),strict=True))
            need(row["counts"]["skips"]<=row["counts"]["direct"] and (arm=="strict" or row["counts"]["skips"]==0),
                 ("impossible native pass counts",row))
        product.append(row)
    return product



def qualify(rows, owners):
    """Compare real Cargo arguments and the native-pass counters from separate processes."""
    result={}
    clean_argv=None
    for arm in ARMS:
        group=[row for row in rows if row["arm"]==arm]
        clean,=[row for row in group if row["phase"]=="clean-new"]
        calls={name:[] for name in owners}
        for call in clean["native"]:
            need(call["owner"] in calls,("unexpected owner",call))
            calls[call["owner"]].append(call["argv"])
        need(all(calls.values()),("missing physical clean-new compiler",arm,tuple(calls)))
        plain={name:sorted(args) for name,args in calls.items()}
        if clean_argv is None:
            clean_argv=plain
        need(plain==clean_argv,("Cargo passed different owner arguments",arm))
        measured=[c for row in group if row["history"]=="edit" for c in row["native"]]
        need(all("counts" not in c for c in measured),"instrumented machine pass entered a measured Cargo command")
        ins=[c for row in group if row["history"]=="clean" for c in row["native"] if "counts" in c]
        counters={k:sum(c["counts"][k] for c in ins) for k in ("installed","machines","direct","skips")}
        if arm!="signed":
            need(counters["installed"]>0 and counters["machines"]>0 and counters["direct"]>0,
                 ("source pass never reached the real compiler backend",arm,counters))
            if arm=="strict":
                need(counters["skips"]>0,("no direct opportunity on this real workflow",counters))
        result[arm]={"inspection":counters,"measured_native_children":len(measured),
                     "unchanged_native_owners":[c["owner"] for row in group if row["phase"]=="unchanged" for c in row["native"]]}
    return {"schema":"ohm-source-pass-physical-v1","owner_argv":clean_argv,"arms":result}
