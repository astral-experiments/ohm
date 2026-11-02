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


def elf_build_id(path):
    """Return the file offset and exact immutable GNU build-ID note from ELF64."""
    notes = []
    with path.open("rb") as f:
        head = f.read(64)
        need(head[:6] == b"\x7fELF\x02\x01", "expected little-endian ELF64 driver")
        phoff = struct.unpack_from("<Q", head, 32)[0]
        stride, count = struct.unpack_from("<HH", head, 54)
        need(stride == 56 and 0 < count < 256, "invalid ELF program header table")
        f.seek(phoff)
        headers = f.read(stride * count)
        for i in range(count):
            kind, _, offset, _, _, size, _, _ = struct.unpack_from("<IIQQQQQQ", headers, i*stride)
            if kind != 4:
                continue
            need(size < 1 << 20, "oversized ELF notes")
            f.seek(offset)
            data, pos = f.read(size), 0
            while pos + 12 <= len(data):
                n, d, typ = struct.unpack_from("<III", data, pos)
                pos += 12
                label = data[pos:pos+n]
                pos += (n+3) & ~3
                need(pos+d <= len(data), "truncated ELF note")
                if label == b"GNU\0" and typ == 3:
                    need(8 <= d <= 64, "invalid GNU build ID")
                    notes.append({"offset": offset+pos, "hex": data[pos:pos+d].hex()})
                pos += (d+3) & ~3
    need(len(notes) <= 1, "multiple GNU file build IDs")
    return notes[0] if notes else None


def executable_segments(path):
    import hashlib
    result=[]
    with path.open("rb") as f:
        head=f.read(64)
        need(head[:7]==b"\x7fELF\x02\x01\x01","expected little endian ELF64")
        offset=struct.unpack_from("<Q",head,32)[0]
        stride,num=struct.unpack_from("<HH",head,54)
        need(stride==56 and 0<num<256,"bad program headers")
        f.seek(offset)
        headers=f.read(stride*num)
        for i in range(num):
            kind,flags,off,vaddr,_,sz,_,_=struct.unpack_from("<IIQQQQQQ",headers,i*stride)
            if kind!=1 or not flags&1 or not sz:
                continue
            need(flags&2==0 and 0<sz<=700*(1<<20),"unexpected writeable/excessive executable segment")
            f.seek(off)
            h=hashlib.sha256(); left=sz
            while left:
                data=f.read(min(left,1<<20))
                need(data,"short executable segment")
                h.update(data);left-=len(data)
            result.append({"offset":off,"vaddr":vaddr,"size":sz,"sha256":h.hexdigest()})
    need(0<len(result)<12,"unexpected executable load count")
    return result


def real_llvm(sdk, manifest):
    root=sdk/"lib"
    elf=[]
    scripts=[]
    for p in root.glob("libLLVM*.so*"):
        if not p.is_file():
            continue
        name=str(p.relative_to(sdk))
        need(sha(p)==manifest[name],"different registered LLVM member")
        with p.open("rb") as f:
            if f.read(4)==b"\x7fELF":
                elf.append(p)
            else:
                need(p.stat().st_size<256,"unexpected LLVM link-time input")
                scripts.append(p)
    need(len(elf)==1,"expected exactly one executing ELF LLVM")
    for p in scripts:
        need(p.read_bytes()==f"INPUT({elf[0].name})\n".encode(),"unrecognised linker-script alias")
    return elf[0]


def binding(path):
    p = path.resolve(strict=True)
    st = p.stat()
    return {"path": str(p), "sha256": sha(p), "device": [os.major(st.st_dev), os.minor(st.st_dev)],
            "inode": st.st_ino, "build_id": elf_build_id(p), "exec_loads": executable_segments(p)}


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
        expected = {n: v[0] for n, v in specs[role].items()}
        driver = sdk / "lib" / native["driver"]
        llvm = real_llvm(sdk, expected)
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
