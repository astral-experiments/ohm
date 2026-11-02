import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from physical import binding, first_load_vaddr, symbols


def call(argv, cwd):
    return subprocess.check_output(argv, cwd=cwd, stderr=subprocess.STDOUT, timeout=60)


def test():
    with tempfile.TemporaryDirectory() as temporary:
        w = Path(temporary)
        (w / "library.c").write_text("int abi(int a){return a+1;}\n")
        (w / "driver.c").write_text("extern int abi(int); int pass(int a){return abi(a);}\n")
        (w / "main.c").write_text("#include <signal.h>\nextern int pass(int); static volatile sig_atomic_t delivered; "
                                  "static void wake(int n){delivered+=(n==SIGUSR1);} "
                                  "int main(void){signal(SIGUSR1,wake);raise(SIGUSR1);return delivered!=1 || pass(16)!=17;}\n")
        for argv in (["cc", "-fPIC", "-shared", "-Wl,--build-id=none", "library.c", "-o", "libqa-llvm.so"],
                     ["cc", "-fPIC", "-shared", "driver.c", "-L.", "-lqa-llvm", "-Wl,-rpath,$ORIGIN", "-o", "libqa-driver.so"],
                     ["cc", "main.c", "-L.", "-lqa-driver", "-Wl,-rpath,$ORIGIN", "-o", "front"]):
            call(argv, w)
        driver, llvm, frontend = (w / name for name in ("libqa-driver.so", "libqa-llvm.so", "front"))
        try:
            symbols(driver, "C")
        except ValueError:
            pass
        else:
            raise AssertionError("accepted a compiler missing all product pass symbols")
        addr, = (int(l.split()[0], 16) for l in call(["nm", "--defined-only", driver], w).decode().splitlines()
                 if l.endswith(" T pass"))
        spec = {"frontend": binding(frontend), "driver": binding(driver), "llvm": binding(llvm),
                "vaddr": first_load_vaddr(driver), "symbols": {"selected": {"name": "pass", "value": addr}},
                "argv": [str(frontend)], "output": str(w / "actual.json")}
        m = w / "input.json"
        m.write_text(json.dumps(spec))
        env = {**os.environ, "LDV_CONTACT_INPUT": str(m), "DEBUGINFOD_URLS": ""}
        cmd = ["gdb", "-nx", "--quiet", "--batch", "-x", str(HERE / "contact.gdb.py"), "--args", str(frontend)]
        acquired = subprocess.run(cmd, cwd=w, env=env, capture_output=True, timeout=35)
        if acquired.returncode or not (w / "actual.json").is_file():
            raise ValueError(("actual GDB fixture failed", acquired.stderr.decode()[-1100:], acquired.stdout.decode()[-900:]))
        proof = json.loads((w / "actual.json").read_bytes())
        assert proof["exit"] == 0 and proof["hits"] == {"selected": 1}
        assert all(proof["loader_fds"][k]["file_sha"] == spec[k]["sha256"] and
                   [e["actual_rx_sha256"] for e in proof["loader_fds"][k]["segments"]] ==
                   [e["sha256"] for e in spec[k]["exec_loads"]] for k in ("driver","llvm"))
        assert proof["loader_fds"]["driver"]["mapped_build_id"][1]==spec["driver"]["build_id"]["hex"]
        assert proof["loader_fds"]["llvm"]["mapped_build_id"] is None
        for wrong in ("inode","file-digest","mapped-note","actual-exec-bytes"):
            false = json.loads(json.dumps(spec))
            if wrong == "inode":
                false["driver"]["inode"] += 1
            elif wrong == "file-digest":
                false["llvm"]["sha256"] = "0" * 64
            elif wrong == "actual-exec-bytes":
                false["llvm"]["exec_loads"][0]["sha256"]="0"*64
            else:
                x = false["driver"]["build_id"]
                x["hex"] = bytes(i ^ 1 for i in bytes.fromhex(x["hex"])).hex()
            false["output"] = str(w / (wrong + ".json"))
            m.write_text(json.dumps(false))
            rejected = subprocess.run(cmd, cwd=w, env=env, capture_output=True, timeout=35)
            assert rejected.returncode and not Path(false["output"]).exists(), ("accepted corrupted evidence",wrong)
        print("Actual loader mmap FD device, inode and SHA, mapped build ID, instructions, argv SIGUSR1 delivery and four negative controls passed.")

def installed(library):
    from physical import sha
    assert sha(library)=="43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
    with tempfile.TemporaryDirectory() as w:
        out=Path(w)
        (out/"driver.c").write_text("extern void LLVMGetVersion(unsigned*,unsigned*,unsigned*); int pass(void){ unsigned a,b,c; LLVMGetVersion(&a,&b,&c); return a==23; }\n")
        (out/"main.c").write_text("extern int pass(void); int main(void){return !pass();}\n")
        call(["cc","-fPIC","-shared","driver.c",library,"-Wl,-rpath,"+str(library.parent),"-o","libqa-driver.so"],out)
        call(["cc","main.c","-L.","-lqa-driver","-Wl,-rpath,$ORIGIN","-Wl,-rpath-link,"+str(library.parent),"-o","front"],out)
        driver, front=out/"libqa-driver.so",out/"front"
        adr,=(int(l.split()[0],16) for l in call(["nm","--defined-only",driver],out).decode().splitlines() if l.endswith(" T pass"))
        spec={"frontend":binding(front),"driver":binding(driver),"llvm":binding(library),"vaddr":first_load_vaddr(driver),
              "symbols":{"selected":{"name":"pass","value":adr}},"argv":[str(front)],"output":str(out/"obs.json")}
        f=out/"in.json";f.write_text(json.dumps(spec))
        r=subprocess.run(["gdb","-nx","--quiet","--batch","-x",str(HERE/"contact.gdb.py"),"--args",front],cwd=out,
            env={**os.environ,"LDV_CONTACT_INPUT":str(f),"DEBUGINFOD_URLS":""},capture_output=True,timeout=120)
        if r.returncode or not (out/"obs.json").exists():
            raise AssertionError(("actual original two-PT_LOAD product",r.stderr[-900:],r.stdout[-500:]))
        v=json.loads((out/"obs.json").read_bytes())
        assert v["exit"]==0 and v["hits"]=={"selected":1} and v["loader_fds"]["llvm"]["mapped_build_id"] is None
        assert len(v["loader_fds"]["llvm"]["segments"])==2
        print("Live authenticated signed LLVM, no GNU build ID, both genuine executable PT_LOADs fully byte-for-byte qualified.")


if __name__ == "__main__":
    test()
    if len(sys.argv)>1:
        installed(Path(sys.argv[1]).resolve(strict=True))
