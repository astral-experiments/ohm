"""Reopen the mixed-debug objects, run their executables, and verify the captured debugger verdicts."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile

here = Path(__file__).resolve().parent
inputs = here / "native-receipt.tar.gz"
dwarfdump = shutil.which("llvm-dwarfdump-18") or shutil.which("llvm-dwarfdump")
assert dwarfdump


def elf_section(data, name):
    assert data[:6] == b"\x7fELF\x02\x01"
    shoff, = struct.unpack_from("<Q", data, 40)
    stride, count, names = struct.unpack_from("<HHH", data, 58)
    assert stride == 64 and 0 < names < count
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + stride * i) for i in range(count)]
    offset, size = headers[names][4:6]
    strings = data[offset:offset + size]
    [row] = [row for row in headers if strings[row[0]:].split(b"\0", 1)[0] == name.encode()]
    offset, size = row[4:6]
    assert size and offset + size <= len(data)
    return data[offset:offset + size]


objects = {}
codes = set()
with tarfile.open(inputs, "r:gz") as archive, tempfile.TemporaryDirectory() as tmp:
    expected = {"contact-verdict.json"}
    for role in "PC":
        for mode in ("ordinary", "disable-range"):
            expected.update(f"{role}-{mode}.{suffix}" for suffix in ("o", "exe", "gdb", "driver.json"))
    assert len(archive.getmembers()) == len(expected)
    assert all(m.name in expected and m.isfile() and m.size < 100000 for m in archive)
    for role in "PC":
        for mode in ("ordinary", "disable-range"):
            prefix = f"{role}-{mode}"
            def body(suffix):
                return archive.extractfile(prefix + "." + suffix).read()
            infile = Path(tmp) / (prefix + ".o")
            infile.write_bytes(body("o"))
            executable = Path(tmp) / (prefix + ".exe")
            executable.write_bytes(body("exe"))
            executable.chmod(0o700)
            verdict = subprocess.check_output([str(executable)], text=True)
            assert verdict == "66 mixed-debug calls matched the independent integer oracle\n"
            run = json.loads(body("driver.json"))
            digest = hashlib.sha256(body("o")).hexdigest()
            assert digest == run["object"] and hashlib.sha256((here / "mixed-inline.ll").read_bytes()).hexdigest() == run["ir"]
            assert run["role"] == role and run["mode"] == mode
            objects[role, mode] = digest
            codes.add(elf_section(body("o"), ".text"))
            subprocess.run([dwarfdump, "--verify", infile], check=True, stdout=subprocess.DEVNULL)
            info = subprocess.check_output([dwarfdump, "--debug-info", "--debug-loclists", infile], text=True)
            assert "DW_TAG_inlined_subroutine" in info and '"inline_witness"' in info and '"full_witness"' in info
            located = [v for v in re.split(r"\n(?=0x[0-9a-f]+:)", info)
                       if "DW_TAG_variable" in v and "DW_AT_location" in v]
            gdb = body("gdb").decode()
            assert "in full_inlined ()" in gdb and "ptrace:" not in gdb
            if mode == "ordinary":
                assert len(located) == 2
                inline, = [v for v in located if '"inline_witness"' in v]
                full, = [v for v in located if '"full_witness"' in v]
                assert "[0x0000000000000006, 0x000000000000001c): DW_OP_reg3 RBX" in inline
                assert "[0x0000000000000026, 0x000000000000003c): DW_OP_reg3 RBX" in full
                assert "inline_witness = 22\n$1 = 22" in gdb
            else:
                assert not located and "inline_witness = <optimized out>\n$1 = <optimized out>" in gdb
    expected_trace = [("line_inline", "guard"), ("line_inline", "fallback"),
                      ("full_branch", "guard"), ("full_branch", "fallback"), ("pure_line", "guard")]
    contact = json.load(archive.extractfile("contact-verdict.json"))
    assert [(r["function"], r["pass"]) for r in contact] == expected_trace
    assert all(r["function_pointer_offset"] == 0 for r in contact)
assert len(codes) == 1
assert objects["C", "ordinary"] == objects["P", "ordinary"] != objects["P", "disable-range"] == objects["C", "disable-range"]
print("Verified four native programs, both live-debugger outcomes and each guarded function")
