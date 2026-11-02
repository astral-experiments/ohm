"""Off-clock causal control for signed Cargo's shared-registry eligibility."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import runtime
from runtime import census,guards,need,put,sha,support,transport


def signed(temp):
    root=temp/"ldv-intact-documentation"
    root.mkdir()
    sdk=root/"sdk"
    original=census.common.SDK
    asset=original["asset"]
    release=json.loads(
        subprocess.check_output(["gh","api","repos/"+transport.REPO+"/releases/tags/ohm-1.99.0-22"]))
    row,=[x for x in release["assets"] if x["id"]==asset["id"]]
    need(not release["draft"] and [row[k] for k in ("name","size","digest")]==[asset["name"],asset["size"],"sha256:"+asset["sha256"]],"wrong released doc tool")
    guards.admit(guards.resources(root,root),entry=True,bootstrap=True)
    archive=root/asset["name"]
    with archive.open("xb") as out:
        subprocess.run(["gh","api","-H","Accept: application/octet-stream","repos/"+transport.REPO+"/releases/assets/"+str(asset["id"])],stdout=out,check=True)
    census.acquire.extract(archive,sdk)
    census.acquire.verify_sdk(sdk)
    need(sum(1 for p in sdk.rglob("*") if p.is_file())==len(original["members"])==79,"incomplete original documentation SDK")
    put(root/"signed.json",{"archive":asset,"members":len(original["members"]),"rustdoc":sha(sdk/"bin/rustdoc"),
                           "manifest":sha(HERE.parent/"ruff-default-owner-pmu/signed-sdk.json")})


def html(kit,real,out):
    source=out/"doc.rs"
    source.write_text("/// An actual signed documentation control.\npub fn qualified() -> usize { 29 }\n")
    version=subprocess.check_output(["rustdoc","+ohm","-vV"],env=kit.base,text=True)
    capture=subprocess.run(["rustdoc","+ohm","-o",out/"html","--crate-name","ldv_layout",source],
        env={**kit.base,"LD_DEBUG":"libs"},capture_output=True,check=True,timeout=60)
    item=out/"html/ldv_layout/fn.qualified.html"
    need(b"An actual signed documentation control." in item.read_bytes(),"missing generated HTML")
    loaded=[Path(p) for p in re.findall(r"calling init:\s+([^\s]+)",capture.stderr.decode()) if Path(p).name.startswith(("librustc_driver-","libLLVM"))]
    driver,=[p for p in loaded if p.name.startswith("librustc_driver-")]
    llvm,=[p for p in loaded if p.name.startswith("libLLVM")]
    bound=census.common.SDK["members"]
    need(driver.samefile(real/"lib"/driver.name) and sha(driver)==bound["lib/"+driver.name][3] and
         sha(llvm)==bound["lib/"+llvm.name][3]==kit.refs[kit.active]["llvm"]["sha"],"foreign documentation library")
    put(out/"html.json",{"version":version,"rustdoc":sha(kit.sdk/"bin/rustdoc"),"driver":sha(driver),"llvm":sha(llvm),"html":sha(item)})


def registry_externs(args):
    paths=[Path(v.partition("=")[2]) for i,v in enumerate(args) if i and args[i-1]=="--extern" and v.startswith("autocfg=")]
    suffixes=[p.suffix for p in paths]
    need(suffixes.count(".rlib")==1 and suffixes.count(".rmeta")<=1 and set(suffixes)<= {".rlib",".rmeta"}
         and len({p.with_suffix("") for p in paths})==1,"incorrect ordinary compiler autocfg inputs")
    return paths


def enroll(temp):
    root,evidence,_=census.paths(); root.mkdir();evidence.mkdir()
    prior=temp/"ldv-qualified-sdks"
    real=temp/"ldv-intact-documentation/sdk"
    census.acquire.verify_sdk(real)
    guards.admit(guards.resources(root,evidence),entry=True,bootstrap=True)
    kit=runtime.Runtime(root,prior,evidence,None)
    work=root/"small-ordinary"
    work.mkdir()
    src=work/"src";src.mkdir()
    text=(src/"main.rs")
    text.write_text('fn main() { println!("layout {}", std::mem::size_of::<Option<&autocfg::AutoCfg>>() > 0); }\n')
    (work/"Cargo.toml").write_text('[package]\nname="ldv-layout"\nversion="0.0.1"\nedition="2021"\n[dependencies]\nautocfg="=1.5.0"\n')
    home=work/"home"; target=work/"target"; build=work/"build"
    (work/"build.rs").write_text('fn main() { println!("cargo::rerun-if-changed=build.rs"); println!("cargo::warning=ldv-layout-doc={}",std::env::var("RUSTDOC").unwrap()); }\n')
    env={**kit.base,"CARGO_HOME":str(home),"CARGO_TARGET_DIR":str(target),"CARGO_BUILD_BUILD_DIR":str(build)}
    runtime.clean(env)
    subprocess.run(["cargo","+ohm","generate-lockfile"],cwd=work,env=env,check=True)
    subprocess.run(["cargo","+ohm","fetch","--locked"],cwd=work,env=env,check=True)
    checksum=json.loads((HERE/"worker.json").read_bytes())["autocfg"]
    need(checksum in (work/"Cargo.lock").read_text(),"wrong real registry dependency")
    archives=list((home/"registry/cache").rglob("*.crate"))
    need(archives and all(p.name=="autocfg-1.5.0.crate" and sha(p)==checksum for p in archives),"unregistered registry or bytes")
    arms={}
    for label,role,withdoc in (("original-missing","P",False),("with-P","P",True),("with-C","C",True),("with-P-return","P",True)):
        kit.select(role)
        out=evidence/label;out.mkdir()
        doc=kit.sdk/"bin/rustdoc"
        if withdoc:
            if not doc.exists():
                doc.symlink_to(real/"bin/rustdoc")
            need(doc.is_symlink() and doc.samefile(real/"bin/rustdoc"),"different submitted documentation executable")
            html(kit,real,out)
        else:
            need(not os.path.lexists(doc),"original did not lack the documentation executable")
        need(not build.exists() and not target.exists(),"old targets in layout diagnostic")
        cargo=["cargo","+ohm","build","--locked","--offline","-j4","--message-format=json"]
        trace=out/"trace";trace.mkdir();(out/"native").mkdir()
        cmd=["/usr/bin/strace","-ff","-qq","-v","-s","131072","-e","trace=%process","-o",str(trace/"exec"),"--",*cargo]
        code=guards.run(cmd,work,env,out,work,out,timeout=120)
        need(code==0,("ordinary tiny build failed",label,code))
        rs,actual=support.observed(out,kit.sdk,"plain",False)
        owner,=[r for r in rs if r["name"]=="ldv_layout" and r["kind"]=="full"]
        operands=registry_externs(owner["argv"])
        artifact,=[p for p in operands if p.suffix==".rlib"]
        need(all(p.is_file() for p in operands),"missing named compiler dependency")
        schema="registries" if withdoc else "workspaces"
        prefix=build if withdoc else target
        m=re.search(r"/debug/build/"+schema+r"/(?:[0-9a-f]+/)?(v2-[0-9a-f]{16})/",str(artifact))
        need(m and artifact.is_relative_to(prefix),("different signed Cargo registry decision",label,str(artifact)))
        result=subprocess.check_output([target/"debug/ldv-layout"],env=env,text=True);need(result=="layout true\n","wrong tiny executable")
        err=(out/"outer.stderr").read_text()
        msg=[line for line in err.splitlines() if "ldv-layout-doc=" in line]
        if not msg:
            msg=[v for v in (out/"outer.stdout").read_text().splitlines() if "ldv-layout-doc=" in v]
        need(msg and all(("ldv-layout-doc="+(str(doc) if withdoc else "rustdoc")) in a for a in msg),"unexpected script RUSTDOC")
        value={"driver":kit.refs[role]["driver"],"root_argv":owner["argv"],"source":sha(text),"autocfg":checksum,
               "actual":actual,"extern":str(artifact),"all_externs":{str(p):sha(p) for p in operands},"shard":m[1],"artifact":sha(artifact),"schema":schema,
               "binary":sha(target/"debug/ldv-layout"),"verdict":result,"rustdoc":str(doc) if withdoc else "rustdoc"}
        put(out/"accepted.json",value);arms[label]=value
        shutil.move(build,work/("finished-build-"+label));shutil.move(target,work/("finished-target-"+label))
    stable=("driver","root_argv","source","autocfg","actual","extern","shard","schema","verdict","rustdoc")
    need(all(arms["with-P"][k]==arms["with-P-return"][k] for k in stable),"one physical compiler registry path changed on a real revisit")
    need(arms["with-P"]["shard"]!=arms["with-C"]["shard"],"different drivers received the same observed shard; inspect raw")
    p,c=arms["with-P"],arms["with-C"]
    def shard_argv(v):
        return [a.replace(v["shard"],"v2-<observed>") for a in v["root_argv"]]
    put(evidence/"layout.json",{"old_missing":arms["original-missing"]["schema"],"with_tool":{k:arms[k]["shard"] for k in ("with-P","with-C","with-P-return")},
        "literal_argv_equal":p["root_argv"]==c["root_argv"],"only_proven_shard_in_owner_argv":shard_argv(p)==shard_argv(c),
        "distinct_driver_sha256":[p["driver"]["sha"],c["driver"]["sha"]],"same_complete_elf":p["binary"]==c["binary"],
        "parent_revisit_byte_equal":{k:p[k]==arms["with-P-return"][k] for k in ("artifact","binary")},
        "artifacts":{k:sha(evidence/k/"accepted.json") for k in arms},"physical_doc":json.loads((real.parent/"signed.json").read_bytes())})
    kit.finish()
    print("Physical Rustdoc/namespace control complete; all measurements excluded.",flush=True)


if __name__=="__main__":
    mode,=sys.argv[1:]
    {"signed":signed,"trial":enroll}[mode](Path(os.environ["RUNNER_TEMP"]).resolve(strict=True))
