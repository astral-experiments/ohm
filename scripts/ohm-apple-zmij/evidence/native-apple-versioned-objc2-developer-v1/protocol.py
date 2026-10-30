"""Verify the transported compiler and Cargo source, Darwin platform, and actual native observations."""
from collections import Counter
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import struct

from counter_scope import scope
from native import P, C, R, S, SIGNED, PACK, TREE, Dataset, compact, sha
from objects import Images

AWARE = "9a102b4519b40f9034aa40533d92c83583dcb289"
CASES = {"signed":S, "classic":R,"aware":AWARE}
V1 = "/dev/null/ohm-recheck-dependent-links"
V2 = V1+"-v2"
HARD = "/dev/null/ohm-untracked-relink-inputs"
SOURCE = json.loads(Path(__file__).with_name("subjects.json").read_bytes())
assert sha(Path(__file__).with_name("subjects.json").read_bytes())=="698e0d1d435517ee0862bd0e7a99f698af20151c4b98ea586aa3d2a5d40b6702"

def sources(v):
    assert sha(v.raw("registration.md")) == "5343de4f60a7c34b2e14d721f8b5bc4deb410f091278aa8d140bfb468e8f47f0"
    signed=v.js("release.json");assert signed["archive"]==SIGNED and S in signed["cargo_version"]
    transported=v.js("versioned-rust-source.json")
    assert transported==[SOURCE["rust-parent"],SOURCE["rust-objc"]]
    p,c=transported
    assert p["files"]["compiler/rustc_interface/src/passes.rs"]==c["files"]["compiler/rustc_interface/src/passes.rs"]=="ca1e085f38ac756aa37baa2edd2395d163bfedae"
    pair=v.js("pair.json");driver,=pair["differ"];assert driver.startswith("lib/librustc_driver") and driver.endswith(".dylib")
    rust={}
    for r,expected in [("P",p),("C",c)]:
        prod=v.js("bootstrap-"+r+"-product.json")
        assert prod==pair["products"][r] and (prod["source"],prod["tree"])==(expected["source"],expected["tree"])
        assert sha(v.raw("bootstrap-"+r+".log"))==prod["build_log"] and prod["build_argv"][-6:]==["build","--stage","1","-j4","compiler/rustc","library"]
        for prop in ("library_tree","stage0_rustc","stage0_cargo"):assert prod[prop]==pair["products"]["P"][prop]
        rust[r]={"source":prod["source"],"tree":prod["tree"],"compiler_tree":expected["compiler_tree"],"driver":prod["runtime"][driver],"members":len(prod["runtime"])}
        for phase in ("producer","consumer","run"):
            root=f"proc-macro/{r}/{phase}/";q=v.js(root+"command.json")
            assert q["exit"]==0 and q["streams"]=={k:sha(v.gz(root+k+".gz")) for k in ("stdout","stderr")}
            if phase=="run":assert q["argv"]==["./reader"] and v.gz(root+"stdout.gz")==b"3\n"
            else:assert q["argv"][:2]==["rustc","+ohm"]
    p_runtime,c_runtime=[pair["products"][r]["runtime"] for r in "PC"]
    assert set(p_runtime)==set(c_runtime) and [k for k in p_runtime if p_runtime[k]!=c_runtime[k]]==[driver]
    make=v.js("run-make.json");log=v.raw("run-make.log")
    assert make=={"source":C,"log":sha(log)} and b"test result: ok. 1 passed; 0 failed" in log and b"suite=run-make mode=run-make (aarch64-apple-darwin)" in log
    cargo={"signed":dict(source=S,sha=signed["cargo"]["sha256"])}
    for name,path in (("classic","cargo293"),("aware","cargo-aware")):
        q=v.js(path+"/product.json");s=v.js(path+"/source.json");rows=[json.loads(l) for l in v.raw(path+"/build.stdout").splitlines()]
        assert q["source"]==s and s["commit"]==CASES[name] and s["lock"]==q["lock"]
        assert s["tree"]==(TREE if name=="classic" else SOURCE["cargo-apple"]["tree"])
        if name=="classic":assert s["entries"]==3114 and s["source_pack"]==PACK
        else:assert s["base"]==v.js("cargo293/source.json") and s["steps"]==[SOURCE["cargo-gnu"], SOURCE["cargo-apple"]]
        assert q["builder_cargo"]==signed["cargo"] and S in q["builder"] and CASES[name] in q["version"] and "aarch64-apple-darwin" in q["version"]
        assert (sha(v.raw(path+"/build.stdout")),sha(v.raw(path+"/build.stderr")))==(q["build_stdout"],q["build_stderr"])
        assert len(rows)==q["typed_outputs"] and rows[-1]=={"reason":"build-finished","success":True}
        leaf,=[a for a in rows if a["reason"]=="compiler-artifact" and a["target"]["name"]=="cargo" and a["target"]["kind"]==["bin"]]
        assert not leaf["fresh"] and set(q["features"])==set(leaf["features"])>= {"all-static","ohm-defaults"}
        assert v.js(path+"/filesystem.json")["FilesystemType"].lower()=="apfs" and v.js(path+"/build.json")["status"]==0
        cargo[name]=dict(source=s["commit"],sha=q["binary"]["sha256"],source_tree=s["tree"],units=len(rows),build=sha(v.raw(path+"/build.json")))
    assert len({r["sha"] for r in cargo.values()})==3
    for r in "PC":
        if v.exists("versioned/sdk-"+r+".json"):
            actual=v.js("versioned/sdk-"+r+".json");assert actual["driver"]["sha256"]==rust[r]["driver"] and actual["cargo"]["sha256"]==cargo["aware"]["sha"] and AWARE in actual["cargo_version"]
            assert v.js("versioned/dyld-"+r+"/verified.json")["loaded"][driver]["sha256"]==rust[r]["driver"]
            rust[r]["std"]=actual["std"];rust[r]["rustc"]=actual["rustc"]["sha256"]
    if "std" in rust["P"] and "std" in rust["C"]:assert (rust["P"]["std"],rust["P"]["rustc"])==(rust["C"]["std"],rust["C"]["rustc"])
    observer=v.js("observer.json");assert observer["exit"]==29 and re.fullmatch(r"[a-f0-9]{64}",observer["ld"])
    return dict(rust=rust,cargo=cargo,driver_member=driver,stock_ld=observer["ld"],signed_archive=SIGNED,run_make=make["log"],calibration=scope(v))

class Receiver(Dataset):
    """Present a selected receiver's provider matrix to the previously qualified native reader."""
    def __init__(self,z,name="aware",root=None):
        super().__init__(z)
        self.prefix="" if "release.json" in self.names else "receipts/"
        self.complete=self.prefix+"release.json" in self.names
        self.root=root or ("provider-matrix" if name=="aware" else "versioned/"+name+"/provider-matrix")
    def resolve(self,n):
        if n.startswith("provider-matrix/"):return self.root+n[len("provider-matrix"):]
        return n
    def raw(self,n):return self.z.read(self.prefix+self.resolve(n))
    def exists(self,n):return self.prefix+self.resolve(n) in self.names

class LocalImages(Images):
    def __init__(self,view):
        super().__init__(view);self.locals={}
    def raw(self,kind,key):
        if kind=="local":
            data=self.view.gz(self.locals[key]+"/program.macho.gz");assert sha(data)==key;return data
        return super().raw(kind,key)

def standalone(v,phase,row,store,prior,root_name,ld_sha):
    data=v.gz(phase+"/program.macho.gz"); digest=sha(data)
    assert data[:8]==bytes.fromhex("cffaedfe0c000001") and struct.unpack_from("<I",data,12)[0]==2 and row["program"]["raw"]==digest
    native=row["native"]
    raw=v.gz(phase+"/exec.json.gz");events=json.loads(raw);body=v.gz(phase+"/stdout.gz");messages=list(map(json.loads,body.splitlines()))
    streams={k:sha(v.gz(phase+"/"+f+".gz")) for k,f in (("stdout","stdout"),("stderr","stderr"),("native_events","exec.json"))}
    assert streams==(row.get("streams") or row["interval"]["streams"])
    assert messages[-1]=={"reason":"build-finished","success":True} and events[0]["argv"]==["cargo","+ohm","build","--locked","--offline","-j4","--message-format=json"]
    real,=[e for e in events if e["argv"][1:]==events[0]["argv"][2:] and PurePosixPath(e["path"]).name in ("cargo","cargo-293","cargo-aware")]
    full=[];only=[];linkers=[]
    for e in events:
        argv=e["argv"]
        if e["path"].endswith("/native/bin/rustc") and "--crate-name" in argv:
            crate=argv[argv.index("--crate-name")+1]
            if crate=="___" and any(a=="--print" or a.startswith("--print=") for a in argv):continue
            (only if any("link-only" in a for a in argv) else full).append(crate)
        if PurePosixPath(e["path"]).name in ("ld","ld-classic","ld-prime","ld64","ld.lld","rust-lld","ld64.lld","wild","wild-ld"):linkers.append(e)
    assert sorted(full)==native["full"] and sorted(only)==native["link_only"] and native["scope"]=="kernel-exec" and native["cargo"]==1
    assert [e["argv"] for e in linkers]==[l["argv"] for l in native["linkers"]]
    assert all("/Xcode" in e["path"] and meta["stock"] and meta["sha"]==ld_sha for e,meta in zip(linkers,native["linkers"]))
    assert len({e["seq"] for e in events})==len(events) and all(e["pid"]>0 for e in events)
    info=row["cgu"];store.locals[digest]=phase
    mains=[e for e in linkers if "-o" in e["argv"] and re.fullmatch(root_name+r"(?:-[a-f0-9]{16})?",PurePosixPath(e["argv"][e["argv"].index("-o")+1]).name)]
    if mains:
        assert len(mains)==1 and v.exists(phase+"/cgu-proof.json") and v.js(phase+"/cgu-proof.json")==info
        cert=store.proof(phase,"local",prior=prior);assert cert["raw"]==digest
    else:
        assert digest in prior and not v.exists(phase+"/cgu-proof.json") and prior[digest]["recipe"]==info["recipe"]
        cert=prior[digest]
    return dict(actual_full=sorted(full),link_only=sorted(only),stock_linkers=len(linkers),reader_links=len(mains),
                cargo_cdhash=real["cdhash"],raw=digest,norm=cert["norm"],module_sha=cert["modules_sha"],module_count=cert["module_count"],output=cert["output_sha"],
                input_bytes=cert["physical_bytes"],streams=streams,typed_count=sum(x["reason"]=="compiler-artifact" for x in messages)),messages
