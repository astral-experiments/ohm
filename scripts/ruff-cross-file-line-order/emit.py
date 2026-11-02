"""Emit one DWARF object using the signed compiler's LLVM shared library."""

import ctypes as ct
import hashlib
import os
from pathlib import Path
import sys


library, template, line, output = sys.argv[1:]
assert 0 < int(line) <= 2**24 - 1
with open(library, 'rb') as f:
    assert hashlib.file_digest(f, 'sha256').hexdigest() == '43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51'
lib = ct.CDLL(library)
ptr, string, integer = ct.c_void_p, ct.c_char_p, ct.c_int


def api(name, result, *arguments):
    function = getattr(lib, 'LLVM' + name)
    function.restype = result
    function.argtypes = arguments
    return function


for suffix in ('TargetInfo', 'Target', 'TargetMC', 'AsmPrinter', 'AsmParser'):
    api('InitializeX86' + suffix, None)()
source = Path(template).read_bytes()
assert source.count(b'B_LINE') == 1
source = source.replace(b'B_LINE', line.encode('ascii'))
ctx = api('ContextCreate', ptr)()
buf = api('CreateMemoryBufferWithMemoryRangeCopy', ptr, string, ct.c_size_t, string)(source, len(source), b'cross-file.ll')
err = string()
module, target = ptr(), ptr()
status = api('ParseIRInContext', integer, ptr, ptr, ct.POINTER(ptr), ct.POINTER(string))(ctx, buf, ct.byref(module), ct.byref(err))
assert status == 0, err.value
triple = b'x86_64-unknown-linux-gnu'
status = api('GetTargetFromTriple', integer, string, ct.POINTER(ptr), ct.POINTER(string))(triple, ct.byref(target), ct.byref(err))
assert status == 0, err.value
tm = api('CreateTargetMachine', ptr, ptr, string, string, string, integer, integer, integer)(target, triple, b'x86-64', b'', 1, 2, 0)
assert tm
layout = api('CreateTargetDataLayout', ptr, ptr)(tm)
api('SetModuleDataLayout', None, ptr, ptr)(module, layout)
status = api('TargetMachineEmitToFile', integer, ptr, ptr, string, integer, ct.POINTER(string))(tm, module, os.fsencode(output), 1, ct.byref(err))
assert status == 0, err.value
