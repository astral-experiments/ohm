"""Run the published compiler's output manager on one verified mixed-debug module."""
import ctypes as ct
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
from pathlib import Path

role, mode = sys.argv[1:]
assert role in ("P", "C") and mode in ("ordinary", "disable-range")
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
sdk = Path("sdk-" + role).resolve()
driver_path, = sdk.glob("librustc_driver-*.so")
llvm_path, = sdk.glob("libLLVM.so.*")
llvm = ct.CDLL(str(llvm_path), mode=ct.RTLD_GLOBAL)
driver = ct.CDLL(str(driver_path))
voidp, string, uint, i32, bit = ct.c_void_p, ct.c_char_p, ct.c_uint, ct.c_int, ct.c_bool
ptrp = ct.POINTER(voidp)
charp = ct.POINTER(string)


def exported(name, result, *args):
    fn = getattr(llvm, name)
    fn.restype = result
    fn.argtypes = args
    return fn


target = b"x86_64-unknown-linux-gnu"
factory = "LLVMRustCreateCoalescingPassManager" if role == "P" else "LLVMRustCreateOutputPassManager"
vtable = "_ZTVN12_GLOBAL__N_120RustCoalescerManagerE" if role == "P" else "_ZTVN12_GLOBAL__N_121RustOutputPassManagerE"
guard = "_ZN12_GLOBAL__N_120LineTableDebugValues20runOnMachineFunctionERN4llvm15MachineFunctionE"
names = {factory, vtable, "LLVMRustWriteOutputFile", "LLVMRustAddLibraryInfo"}
if role == "C":
    names.add(guard)
offsets = {}
with subprocess.Popen(["nm", "-an", str(driver_path)], stdout=subprocess.PIPE, text=True) as proc:
    for line in proc.stdout:
        parts = line.split()
        if len(parts) == 3 and parts[2] in names:
            assert parts[2] not in offsets and parts[1] in ("d", "D", "t", "T")
            offsets[parts[2]] = int(parts[0], 16)
assert offsets.keys() == names
maps = [line.split(maxsplit=5) for line in Path("/proc/self/maps").read_text().splitlines()]
addresses = [int(row[0].split("-")[0], 16) for row in maps
             if len(row) == 6 and row[5] == str(driver_path) and int(row[2], 16) == 0]
base, = addresses
assert ct.string_at(base, 4) == b"\x7fELF"
executable = [tuple(int(v, 16) for v in row[0].split("-")) for row in maps
              if len(row) == 6 and row[5] == str(driver_path) and "x" in row[1]]


def bound(name, result, *args):
    pc = base + offsets[name]
    assert any(start <= pc < stop for start, stop in executable)
    return ct.CFUNCTYPE(result, *args)(pc)


for suffix in ("TargetInfo", "Target", "TargetMC", "AsmPrinter", "AsmParser"):
    exported("LLVMInitializeX86" + suffix, None)()
options = [b"mixed-debug-replay"]
if mode == "disable-range":
    options += [b"--livedebugvalues-input-bb-limit=0", b"--livedebugvalues-input-dbg-value-limit=0"]
argv = (string * (len(options) + 1))(*options, None)
exported("LLVMParseCommandLineOptions", None, i32, charp, string)(len(options), argv, None)
ctx = exported("LLVMContextCreate", voidp)()
source = Path("mixed-inline.ll").read_bytes()
buf = exported("LLVMCreateMemoryBufferWithMemoryRangeCopy", voidp, string, ct.c_size_t, string)(
    source, len(source), b"mixed-inline.ll")
error = string()
module = voidp()
status = exported("LLVMParseIRInContext", i32, voidp, voidp, ptrp, charp)(ctx, buf, ct.byref(module), ct.byref(error))
assert status == 0 and module.value, error.value
assert exported("LLVMVerifyModule", i32, voidp, i32, charp)(module, 2, ct.byref(error)) == 0, error.value
arch = voidp()
status = exported("LLVMGetTargetFromTriple", i32, string, ptrp, charp)(target, ct.byref(arch), ct.byref(error))
assert status == 0 and arch.value, error.value
tm = exported("LLVMCreateTargetMachine", voidp, voidp, string, string, string, i32, i32, i32)(
    arch, target, b"x86-64", b"", 1, 2, 0)
assert tm
layout = exported("LLVMCreateTargetDataLayout", voidp, voidp)(tm)
exported("LLVMSetModuleDataLayout", None, voidp, voidp)(module, layout)
if role == "P":
    pm = bound(factory, voidp, voidp, bit)(tm, True)
else:
    pm = bound(factory, voidp, voidp, voidp, bit)(tm, module, True)
assert pm
# The Itanium ABI places two words before the virtual table's address point.
assert ct.c_void_p.from_address(pm).value == base + offsets[vtable] + 2 * ct.sizeof(voidp)
if os.environ.get("OHM_MIXED_CONTACT") == "1":
    assert role == "C" and mode == "ordinary"
    tracing = [s for s in Path("/proc/self/status").read_text().splitlines() if s.startswith("TracerPid:")]
    assert len(tracing) == 1 and int(tracing[0].split()[1]) > 0
    lookup = exported("LLVMGetNamedFunction", voidp, voidp, string)
    functions = {name: lookup(module, name.encode()) for name in ("line_inline", "full_branch", "pure_line")}
    assert all(functions.values()) and len(set(functions.values())) == 3
    fallback = "_ZN4llvm19LiveDebugValuesPass3runERNS_15MachineFunctionERNS_15AnalysisManagerIS1_JEEE"
    probes = {"guard": base + offsets[guard], "fallback": ct.cast(getattr(llvm, fallback), voidp).value}
    Path("contact-input.json").write_text(json.dumps({"functions": functions, "probes": probes, "pid": os.getpid()}))
    os.kill(os.getpid(), signal.SIGUSR2)
exported("LLVMAddAnalysisPasses", None, voidp, voidp)(tm, pm)
bound("LLVMRustAddLibraryInfo", None, voidp, voidp, voidp, bit)(tm, pm, module, False)
dst = Path(role + "-" + mode + ".o")
rc = bound("LLVMRustWriteOutputFile", i32, voidp, voidp, voidp, string, string, i32, bit)(
    tm, pm, module, os.fsencode(dst), None, 1, True)
assert rc == 0 and dst.read_bytes()[:4] == b"\x7fELF", rc
print(json.dumps({"role": role, "mode": mode, "object": hashlib.sha256(dst.read_bytes()).hexdigest(),
                  "ir": hashlib.sha256(source).hexdigest(), "factory": factory, "vtable": vtable,
                  "offsets": offsets}))
