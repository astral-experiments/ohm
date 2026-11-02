"""Observe actual GNU -lutil resolution for Ruff's own constructors executable on Cargo #330."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bisect330 as b
import census
import wild_reads

W,E,SDK=census.paths() if "RUNNER_TEMP" in os.environ else (None,None,None)
HERE=Path(__file__).resolve().parent
TRIPLE="x86_64-unknown-linux-gnu"
CASES=("shadow","malformed","nested-missing","repair","restored")
ROLES=("parent","child")


def physical(path):
    try:s=path.stat()
    except FileNotFoundError:return None
    return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def paths_from(work):
    return work,work/"evidence",work/"rustup/toolchains/ohm"


def single(src,work,role,phase):
    global W,E,SDK
    W,E,SDK=paths_from(work)
    env=json.loads((W/"admitted-env.json").read_bytes());assert os.geteuid()==(W/("cargo-"+role)).stat().st_uid != 0
    conf=json.loads((E/"constructors-input-route.json").read_bytes())
    visible=Path(conf["visible"]);root=E/role/phase
    assert not root.exists()
    state={"uid":os.getuid(),"effective_uid":os.geteuid(),"mnt":os.readlink("/proc/self/ns/mnt"),
           "provider":str(visible),"provider_stat":physical(visible),"original_view":conf["namespace"],
           "provider_sha256":census.sha(visible) if visible.is_file() else None,
           "gccdir_mount":subprocess.check_output(["findmnt","-rn","-T",conf["gccdir"],"-o","TARGET,SOURCE,FSTYPE,OPTIONS"],text=True).strip()}
    if conf["kind"]=="system-overlay":
        assert state["mnt"]!=conf["namespace"] and "overlay" in state["gccdir_mount"] and "ro," in state["gccdir_mount"]
    else: assert visible.is_relative_to(SDK) and state["mnt"]==conf["namespace"]
    census.put(E/role/(phase+"-view.json"),state)
    detail=b.visit(root,b.CONSTRUCTORS,src,env,"constructors",trace_files=phase in ("audit-absent","shadow","malformed","nested-missing") and role=="child")
    if phase in ("audit-absent","shadow","malformed","nested-missing") and role=="child":
        wild_reads.capture(root,whole_cost=phase=="audit-absent",visible=visible)
    print("observed",phase,detail["exit"],detail.get("elf"),"wild",detail["wild"],flush=True)


def native_value(record):
    if record["exit"]:return None
    s=record["native"]
    assert "test main ... ok" in s and "1 passed; 0 failed" in s
    hits=[v for v in (29,41) if f"chosen-gnu-provider-{v}\n" in s]
    assert len(hits)<=1
    return hits[0] if hits else 0


def run(src):
    assert census.git(src,"rev-parse","HEAD")==census.RUFF and census.sha(src/"Cargo.lock")==census.LOCK
    assert os.getuid()!=0 and not any(k in os.environ for k in ("GH_TOKEN","GITHUB_TOKEN","RUSTFLAGS","RUSTC_WRAPPER","LD_PRELOAD"))
    assert shutil.disk_usage(W).free>=40*1024**3
    kit=json.loads((E/"identity.json").read_bytes())["sdk"]
    assert census.acquire.verify_sdk(SDK)==kit
    env=census.environment(W,SDK)
    census.put(W/"admitted-env.json",env)
    cp=W/"system-copy";cp.mkdir()
    for path in ("lower","earlier","objects"): (cp/path).mkdir()
    gccdir=Path(subprocess.check_output(["gcc","-print-file-name=libgcc.a"],text=True).strip()).resolve(strict=True).parent
    assert str(gccdir).startswith("/usr/lib/gcc/x86_64-linux-gnu/") and gccdir.name.isdigit()
    system=gccdir/"libutil.so";assert not system.exists() and not system.is_symlink()
    oldns=os.readlink("/proc/self/ns/mnt"); saved_gccdir=physical(gccdir)
    def mount_cmd(action):
        return ["sudo","-n","unshare","--mount","--propagation","private","--","/bin/bash",str(HERE/"private-search.sh"),action,str(W),str(gccdir),oldns,str(os.getuid()),str(os.getgid())]
    probe=subprocess.run(mount_cmd("probe"),capture_output=True,text=True,timeout=30)
    # This one-shot gate precedes compiling or changing any input. Both routes retain all signed bytes.
    if probe.returncode==0:
        kind="system-overlay"; provider=cp/"earlier/libutil.so"; visible=system
    else:
        kind="private-sdk"; provider=SDK/"lib/rustlib"/TRIPLE/"lib/libutil.so"; visible=provider
    assert not provider.exists() and not provider.is_symlink()
    config={"kind":kind,"visible":str(visible),"private_backing":str(provider),"gccdir":str(gccdir),
            "namespace":oldns,"gate":{"exit":probe.returncode,"stdout":probe.stdout,"stderr":probe.stderr},"outside_gccdir":saved_gccdir}
    census.put(E/"constructors-input-route.json",config);print("admitted",config,flush=True)
    source=cp/"objects/hook.c"
    source.write_text('#include <unistd.h>\n#include <string.h>\nextern char *program_invocation_short_name;\n'
                      '#define S_(v) #v\n#define S(v) S_(v)\n__attribute__((constructor)) static void loaded(void) {\n'
                      ' const char *n=program_invocation_short_name; if(n && strncmp(n,"constructors-",13)==0) {\n'
                      ' static const char t[]="chosen-gnu-provider-" S(VALUE) "\\n"; (void)write(1,t,sizeof(t)-1); } }\n')
    for val in (29,41):subprocess.run(["/usr/bin/cc","-c","-fPIC","-O2",f"-DVALUE={val}",source,"-o",cp/f"objects/hook{val}.o"],check=True)
    shutil.copytree(cp/"objects",E/"hook-inputs")
    obj=cp/"objects/active.o";script=f"INPUT ( {obj} )\n".encode()
    expected={x["name"]+"-"+x["version"]+".crate":x["checksum"] for x in tomllib.loads((src/"Cargo.lock").read_text())["package"] if "source" in x}
    assert len(expected)==498
    os.rename(SDK/"bin/cargo",W/"signed22-cargo")
    all_roles={}
    for role in ROLES:
        f=E/role;f.mkdir();(W/"home").mkdir();os.link(W/("cargo-"+role),SDK/"bin/cargo")
        assert census.sha(SDK/"bin/cargo")==b.SOURCE[role][1] and b.SOURCE[role][0] in subprocess.check_output(["cargo","+ohm","-vV"],env=env,text=True)
        with (f/"fetch.log").open("xb") as out:subprocess.run(["cargo","+ohm","fetch","--locked"],env=env,cwd=src,stdout=out,stderr=out,check=True)
        got={p.name:census.sha(p) for p in (W/"cargo/registry/cache").glob("*/*.crate")};assert got==expected;census.put(f/"registry.json",got)
        def visit(phase):
            args=[str(src),str(W),role,phase]
            if kind=="system-overlay":cmd=mount_cmd("visit")+[sys.executable,str(Path(__file__).resolve()),*args]
            else:cmd=[sys.executable,"-IB","-u",str(Path(__file__).resolve()),"visit",*args]
            subprocess.run(cmd,check=True,timeout=1200)
            assert physical(gccdir)==saved_gccdir and not system.exists() and not system.is_symlink()
            return json.loads((f/phase/"result.json").read_bytes())
        def store(label,restore=False):
            for name in ("target","build"):
                active=W/name; parked=W/(role+"-"+label+"-"+name)
                a,d=(parked,active) if restore else (active,parked)
                if a.exists():assert not d.exists();os.rename(a,d)
        result={}
        initial=visit("cold");ordinary=visit("ordinary"); audit=visit("audit-absent")
        assert all(native_value(r)==0 for r in (initial,ordinary,audit))
        assert [bool(r["wild"]) for r in (ordinary,audit)]==[role=="child"]*2
        store("warm");force=visit("independent-train");assert native_value(force)==0;store("forced");store("warm",True)
        for case in CASES:
            if case=="shadow":
                shutil.copyfile(cp/"objects/hook29.o",obj)
                with provider.open("xb") as out:out.write(script)
            elif case=="malformed":
                before=physical(provider);pstat=provider.stat()
                provider.write_bytes(b"!"*len(script));os.utime(provider,ns=(pstat.st_atime_ns,pstat.st_mtime_ns));after=physical(provider)
                assert before[:8]==after[:8];census.put(f/"restamp.json",{"before":before,"after":after})
            elif case=="nested-missing":
                provider.write_bytes(script);obj.unlink()
            elif case=="repair":
                shutil.copyfile(cp/"objects/hook41.o",obj)
            else:provider.unlink()
            warm=visit(case);store("warm")
            # Empty roots keep the identical absolute paths and real toolchain. Also force only Ruff’s root for invalid states.
            clean=visit(case+"-empty");store("empty-"+case)
            forced=None
            if case in ("malformed","nested-missing"):
                store("forced",True)
                with (f/(case+"-clean-cmd.log")).open("xb") as log:
                    subprocess.run(["cargo","+ohm","clean","-p","ruff_text_size","--locked","--offline"],env=env,cwd=src,stdout=log,stderr=log,check=True)
                forced=visit(case+"-target-forced");store("forced")
            store("warm",True)
            result[case]={"warm":[warm["exit"],native_value(warm),warm.get("elf"),warm["rustc"],warm["wild"]],
                          "empty":[clean["exit"],native_value(clean),clean.get("elf"),clean["rustc"],clean["wild"]],
                          "forced":[forced["exit"],native_value(forced),forced.get("elf"),forced["rustc"],forced["wild"]] if forced else None}
        assert not provider.exists() and physical(gccdir)==saved_gccdir
        if obj.exists():obj.unlink()
        os.unlink(SDK/"bin/cargo")
        for name in ("home","cargo","target","build"):
            if (W/name).exists():os.rename(W/name,W/(role+"-final-"+name))
        all_roles[role]=result;census.put(f/"contrasts.json",result)
    os.rename(W/"signed22-cargo",SDK/"bin/cargo")
    assert all(v[:6]==kit[k][:6] for k,v in census.acquire.verify_sdk(SDK).items())
    assert not census.git(src,"status","--porcelain=v1") and not system.exists()
    census.put(E/"constructors-inputs-complete.json",{"route":kind,"source":census.RUFF,"lock":census.LOCK,"roles":all_roles})


if __name__=="__main__":
    if sys.argv[1]=="visit":single(Path(sys.argv[2]).resolve(strict=True),Path(sys.argv[3]).resolve(strict=True),*sys.argv[4:])
    elif sys.argv[1]=="run":run(Path(sys.argv[2]).resolve(strict=True))
    else:raise SystemExit(2)
