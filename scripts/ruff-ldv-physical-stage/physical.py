"""Bind the linked LLVM pass bodies to real, unmodified, off-clock stage1 compilers."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capsule import HOST, need, save, sha

SCOPED = "(anonymous namespace)::"
COALESCER = SCOPED + "RegisterCoalescerLegacy::runOnMachineFunction(llvm::MachineFunction&)"
CUSTOM_LDV = SCOPED + "LineTableDebugValues::runOnMachineFunction(llvm::MachineFunction&)"
FACTORIES = {"P": "LLVMRustCreateCoalescingPassManager", "C": "LLVMRustCreateOutputPassManager"}
MANAGERS = {r: SCOPED + n + "::add(llvm::Pass*)" for r, n in
            (("P", "RustCoalescerManager"), ("C", "RustOutputPassManager"))}


def symbols(driver, role):
    all_names = {COALESCER, CUSTOM_LDV, *FACTORIES.values(), *MANAGERS.values()}
    found = {}
    with subprocess.Popen(["nm", "--defined-only", "--demangle", driver],
                          stdout=subprocess.PIPE, text=True) as nm:
        for row in nm.stdout:
            fields = row.rstrip().split(maxsplit=2)
            if len(fields) == 3 and fields[2] in all_names:
                address, kind, name = fields
                need(kind in ("T", "t") and name not in found, ("unexpected pass symbol", row))
                found[name] = int(address, 16)
        need(nm.wait() == 0, "unreadable complete product symbol table")
    names = {"factory": FACTORIES[role], "manager": MANAGERS[role], "coalescer": COALESCER}
    if role == "C":
        names["ldv"] = CUSTOM_LDV
    need(set(found) == set(names.values()), ("wrong set of actual builtin pass bodies", role, sorted(found)))
    return {k: {"name": n, "value": found[n]} for k, n in names.items()}


def symbol_inventory(stage, role):
    driver, = (stage / "lib").glob("librustc_driver-*.so")
    return {"role": role, "driver": driver.name, "sha256": sha(driver), "symbols": symbols(driver, role)}


def first_load_vaddr(elf):
    with elf.open("rb") as f:
        header = f.read(64)
        need(header[:7] == b"\x7fELF\x02\x01\x01" and int.from_bytes(header[16:18], "little") == 3,
             "expected ELF64 little-endian ET_DYN")
        phoff = struct.unpack_from("<Q", header, 32)[0]
        entsize, number = struct.unpack_from("<HH", header, 54)
        need(entsize == 56 and 0 < number < 100, "invalid program headers")
        f.seek(phoff)
        for _ in range(number):
            kind, flags, offset, vaddr, _, size, _, _ = struct.unpack("<IIQQQQQQ", f.read(entsize))
            if kind == 1 and offset == 0 and size >= 64:
                return vaddr
    raise ValueError("missing offset-zero PT_LOAD")


def binding(path):
    p = path.resolve(strict=True)
    st = p.stat()
    return {"path": str(p), "sha256": sha(p), "device": [os.major(st.st_dev), os.minor(st.st_dev)],
            "inode": st.st_ino}


def contact(root):
    from capsule import admit
    specs = admit(root / "capsule")
    work = root / "physical-contact"
    work.mkdir()
    source = work / "probe.rs"
    source.write_text(
        '#![no_std]\n#[no_mangle] #[inline(never)]\n'
        'pub extern "C" fn live_value(x: u64, y: u64) -> u64 { x.rotate_left(7) ^ y.wrapping_mul(11) }\n'
    )
    result = {}
    for role, label in (("P", "normal"), ("C", "defer")):
        sdk = root / "reopened" / label
        native = symbol_inventory(sdk, role)
        recorded = json.loads((root / "logs" / ("ldv-driver-" + role + ".json")).read_bytes())
        need(native == recorded, "different physical compiler from bootstrap")
        libraries = [p for p in (sdk / "lib").glob("libLLVM*.so*") if p.is_file()]
        real_llvm = {binding(p)["sha256"]: p for p in libraries}
        need(len(real_llvm) == 1, "different actual LLVM payloads")
        expected = {n: v[0] for n, v in specs[role].items()}
        driver = sdk / "lib" / native["driver"]
        llvm = next(iter(real_llvm.values()))
        need(all(sha(p) == expected[str(p.relative_to(sdk))] for p in (sdk / "bin/rustc", driver, llvm)),
             "unregistered frontend, driver or LLVM")
        for debug in ("line-tables-only", "2"):
            tag = role + ("-line" if debug == "line-tables-only" else "-full")
            photo = root / "logs" / ("physical-" + tag)
            photo.mkdir()
            output = work / "probe.o"
            need(not output.exists(), "preexisting object")
            argv = [str(sdk / "bin/rustc"), "--crate-name", "ohm_ldv_work", "--crate-type=lib", "--edition=2021",
                    "-Copt-level=1", "-Cdebug-assertions=yes", "-Cdebuginfo=" + debug,
                    "-Ccodegen-units=1", "-Clto=off", "--emit=obj", "-o", str(output), str(source)]
            record = {"argv": argv, "frontend": binding(sdk / "bin/rustc"), "driver": binding(driver),
                      "llvm": binding(llvm), "vaddr": first_load_vaddr(driver),
                      "symbols": native["symbols"], "output": str(photo / "observed.json")}
            save(photo / "input.json", record)
            env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ") if k in os.environ}
            env.update(LD_LIBRARY_PATH=str(sdk / "lib"), LC_ALL="C", GDBHISTFILE="/dev/null",
                       LDV_CONTACT_INPUT=str(photo / "input.json"), DEBUGINFOD_URLS="")
            with (photo / "gdb.stdout").open("xb") as stdout, (photo / "gdb.stderr").open("xb") as stderr:
                proc = subprocess.run(["gdb", "--quiet", "--batch", "-nx", "-x", str(HERE / "contact.gdb.py"),
                                       "--args", *argv], cwd=work, env=env, stdout=stdout, stderr=stderr, timeout=240)
            need(proc.returncode == 0 and (photo / "observed.json").is_file() and output.is_file(),
                 ("could not contact the native compiler", tag, proc.returncode))
            observed = json.loads((photo / "observed.json").read_bytes())
            hits = observed["hits"]
            need(observed["exit"] == 0 and all(hits[k] > 0 for k in ("factory", "manager", "coalescer"))
                 and (hits.get("ldv", 0) > 0) == (role == "C" and debug == "line-tables-only"),
                 ("unexpected real pass entries", tag, hits))
            result[tag] = {"object": sha(output), "bytes": output.stat().st_size, "hits": hits,
                           "trace": sha(photo / "observed.json"), "source": sha(source)}
            output.rename(photo / "probe.o")
    for level in ("line", "full"):
        need(result["P-" + level]["object"] == result["C-" + level]["object"],
             ("different full object in source-bound contact", level))
    save(root / "logs" / "physical-contact.json", result)


if __name__ == "__main__":
    need(sys.argv[1:] == ["contact"], "expected contact mode")
    contact(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-branch-object-qa")
