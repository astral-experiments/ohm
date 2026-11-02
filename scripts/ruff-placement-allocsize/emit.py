"""Recompute the six OSP records and clean objects with the pinned LLVM and Rust wrapper."""

import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--llvm", type=Path, required=True)
parser.add_argument("--wrapper", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
seen = json.loads((root / "observed.json").read_bytes())
with args.llvm.open("rb") as libfile:
    assert hashlib.file_digest(libfile, "sha256").hexdigest() == seen["llvm_sha256"]
library = ct.CDLL(str(args.llvm.resolve()), mode=ct.RTLD_GLOBAL)
wrapper = ct.CDLL(str(args.wrapper.resolve()))
p, s, i, z = ct.c_void_p, ct.c_char_p, ct.c_int, ct.c_size_t
out = ct.POINTER(p)


def api(name, result, *types):
    function = getattr(library, "LLVM" + name)
    function.restype = result
    function.argtypes = types
    return function


for suffix in ("TargetInfo", "Target", "TargetMC", "AsmPrinter", "AsmParser"):
    api("InitializeX86" + suffix, None)()
cb = ct.CFUNCTYPE(None, p, p, z)
compute = wrapper.LLVMRustGetSourcePlacement
compute.argtypes, compute.restype = [p, p, cb], ct.c_bool
triple = b"x86_64-unknown-linux-gnu"
target, error = p(), p()
assert api("GetTargetFromTriple", i, s, out, out)(triple, ct.byref(target), ct.byref(error)) == 0


def bitcode(module):
    buf = api("WriteBitcodeToMemoryBuffer", p, p)(module)
    start = api("GetBufferStart", p, p)(buf)
    size = api("GetBufferSize", z, p)(buf)
    data = ct.string_at(start, size)
    api("DisposeMemoryBuffer", None, p)(buf)
    return data


with tarfile.open(root / "objects.tar.gz") as archive, tempfile.TemporaryDirectory() as directory:
    for mode in ("definition-and-call", "definition-only", "no-allocsize"):
        for n in (16, 32):
            name = f"{mode}-{n}"
            source = archive.extractfile(name + ".ll").read()
            ctx = api("ContextCreate", p)()
            buf = api("CreateMemoryBufferWithMemoryRangeCopy", p, s, z, s)(source, len(source), b"candidate.rs")
            module = p()
            assert api("ParseIRInContext", i, p, p, out, out)(ctx, buf, ct.byref(module), ct.byref(error)) == 0
            api("SetModuleIdentifier", None, p, s, z)(module, b"candidate.rs", len(b"candidate.rs"))
            original = bitcode(module)
            received = []
            copy = cb(lambda _, data, length: received.append(ct.string_at(data, length)))
            assert compute(module, None, copy)
            assert received == [archive.extractfile(name + ".wire").read()]
            assert bitcode(module) == original
            machine = api("CreateTargetMachine", p, p, s, s, s, i, i, i)(
                target, triple, b"x86-64", b"+sse,+sse2", 1, 2, 0
            )
            options = api("CreatePassBuilderOptions", p)()
            assert not api("RunPasses", p, p, s, p, p)(module, b"default<O1>", machine, options)
            obj = Path(directory) / (name + ".o")
            rc = api("TargetMachineEmitToFile", i, p, p, s, i, out)(
                machine, module, os.fsencode(obj), 1, ct.byref(error)
            )
            assert rc == 0 and obj.read_bytes() == archive.extractfile(name + ".o").read()
            api("DisposePassBuilderOptions", None, p)(options)
            api("DisposeModule", None, p)(module)
            api("DisposeTargetMachine", None, p)(machine)
            api("ContextDispose", None, p)(ctx)
            print(name, "matched")
