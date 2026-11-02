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
        (w / "main.c").write_text("extern int pass(int); int main(void){return pass(16)!=17;}\n")
        for argv in (["cc", "-fPIC", "-shared", "library.c", "-o", "libqa-llvm.so"],
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
                   proof["loader_fds"][k]["mapped_build_id"][1] == spec[k]["build_id"]["hex"] for k in ("driver","llvm"))
        for wrong in ("inode","file-digest","mapped-note"):
            false = json.loads(json.dumps(spec))
            if wrong == "inode":
                false["driver"]["inode"] += 1
            elif wrong == "file-digest":
                false["llvm"]["sha256"] = "0" * 64
            else:
                x = false["driver"]["build_id"]
                x["hex"] = bytes(i ^ 1 for i in bytes.fromhex(x["hex"])).hex()
            false["output"] = str(w / (wrong + ".json"))
            m.write_text(json.dumps(false))
            rejected = subprocess.run(cmd, cwd=w, env=env, capture_output=True, timeout=35)
            assert rejected.returncode and not Path(false["output"]).exists(), ("accepted corrupted evidence",wrong)
        print("Actual loader mmap FD device, inode and SHA, mapped build ID, instructions, argv and three negative controls passed.")


if __name__ == "__main__":
    test()
