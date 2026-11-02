"""Read genuine signed LLVM23 bitcode. No native code is generated."""

import ctypes
from ctypes import POINTER, c_char_p, c_void_p, c_size_t, byref, string_at
from pathlib import Path
from collections import defaultdict
import hashlib, json, re, struct


def sha(x):
    return hashlib.sha256(x).hexdigest()


FILE = "crates/ruff_workspace/src/options.rs"
MDEF = re.compile(r"^!(\d+) = (?:distinct )?!(\w+)\((.*)\)$")
STR = re.compile(
    r'^@(\d+) = private unnamed_addr constant \[(\d+) x i8\] c"(.*)", align 1$'
)
SHAPE = re.compile(
    r'^@(\d+) = private unnamed_addr constant <\{ ptr, \[16 x i8\] \}> <\{ ptr @(\d+), \[16 x i8\] c"(.*)" \}>, align 8$'
)
LINE = re.compile(r"(\b(?:line|scopeLine): )(\d+)")
CHECK = re.compile(r'(\bchecksumkind: CSK_MD5, checksum: ")([0-9a-f]{32})(")')
DITYP = {
    "DILocation",
    "DISubprogram",
    "DILexicalBlock",
    "DILabel",
    "DILocalVariable",
    "DIDerivedType",
    "DICompositeType",
}
ROLES = (
    "3c77dcc2a5c04fc0c54ce95cd51068734015f3e0",
    "088b7b5f77fcb05994fd2a17cbc940cd9edb341a",
)


def unesc(s):
    raw = s.encode("ascii")
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] != 92:
            out.append(raw[i])
            i += 1
        elif raw[i + 1] == 92:
            out.append(92)
            i += 2
        else:
            out.append(int(raw[i + 1 : i + 3], 16))
            i += 3
    return bytes(out)


def debug_key(text, bytes_of_source, tables_sink=None):
    md5 = hashlib.md5(bytes_of_source).hexdigest()
    rows = text.splitlines(keepends=True)
    nd = {}
    files = {}
    source_ids = set()
    lines_by_file = defaultdict(set)
    keys = {}
    for r in rows:
        m = MDEF.fullmatch(r.rstrip("\n"))
        if m:
            nd[m[1]] = (m[2], m[3])

    def fname(i, stack=()):
        if i in files:
            return files[i]
        assert i not in stack
        kind, r = nd[i]
        if kind == "DIFile":
            n = re.search(r'(?:^|, )filename: "([^"]*)"', r)
            assert n
            d = re.search(r'(?:^|, )directory: "([^"]*)"', r)
            f = str(Path(d[1] if d else "") / n[1])
        else:
            p = re.search(r"(?:^|, )file: !(\d+)(?:,|$)", r) or re.search(
                r"(?:^|, )scope: !(\d+)(?:,|$)", r
            )
            f = fname(p[1], (*stack, i)) if p and p[1] in nd else None
        files[i] = f
        return f

    for i, (t, r) in nd.items():
        p = fname(i)
        if not p:
            continue
        if t == "DIFile" and (p == FILE or p.endswith("/" + FILE)):
            mat = CHECK.search(r)
            assert mat and mat[2] == md5, (p, md5, r)
            source_ids.add(i)
        if t not in DITYP:
            continue
        lines_by_file[p].update(int(m[2]) for m in LINE.finditer(r) if m[2] != "0")
    tables = {p: sorted(s) for p, s in lines_by_file.items()}
    order = {p: {n: i + 1 for i, n in enumerate(xs)} for p, xs in tables.items()}
    if tables_sink is not None:
        assert not tables_sink
        tables_sink.update(tables)

    def project_rows(lines, restore, checksum):
        out = []
        change_count = 0
        for row in lines:
            m = MDEF.fullmatch(row.rstrip("\n"))
            if m:
                i = m[1]
                kind = m[2]
                p = files.get(i)
                if checksum and i in source_ids:
                    xx = CHECK.search(row)
                    assert xx[2] == ("0" * 32 if restore else md5)
                    for_hex = md5 if restore else "0" * 32
                    row = CHECK.sub(lambda a: a[1] + for_hex + a[3], row)
                if p and kind in DITYP:

                    def cv(v):
                        nonlocal change_count
                        n = int(v[2])
                        out = (tables[p][n - 1] if restore else order[p][n]) if n else 0
                        change_count += out != n
                        return v[1] + str(out)

                    row = LINE.sub(cv, row)
            out.append(row)
        return "".join(out), change_count

    dense, n = project_rows(rows, False, True)
    canon, c = project_rows(rows, False, False)
    decoded, _ = project_rows(dense.splitlines(keepends=True), True, True)
    assert decoded == text
    return dense, dict(
        files_with_lines=len(tables),
        distinct_positive_lines=sum(map(len, tables.values())),
        source_file_md5=md5,
        source_md5_instances=len(source_ids),
        rendered_line_fields_changed=n,
        with_real_checksum=sha(canon.encode()),
        tables_sha256=sha(json.dumps(tables, sort_keys=True).encode()),
        lossless_debug_roundtrip=True,
    )


class SignedLLVM:
    def __init__(self, path):
        with path.open("rb") as f:
            assert (
                hashlib.file_digest(f, "sha256").hexdigest()
                == "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
            )
        self.lib = ctypes.CDLL(str(path))
        P, U, I, S, B = c_void_p, ctypes.c_uint, ctypes.c_int, c_size_t, c_char_p
        PP = POINTER(P)
        functions = {
            "ContextCreate": (P, []),
            "ContextDispose": (None, [P]),
            "CreateMemoryBufferWithMemoryRangeCopy": (P, [P, S, B]),
            "DisposeMemoryBuffer": (None, [P]),
            "ParseBitcodeInContext2": (I, [P, P, PP]),
            "DisposeModule": (None, [P]),
            "WriteBitcodeToMemoryBuffer": (P, [P]),
            "GetBufferStart": (P, [P]),
            "GetBufferSize": (S, [P]),
            "StripModuleDebugInfo": (I, [P]),
            "IsDeclaration": (I, [P]),
            "GetValueName2": (P, [P, POINTER(S)]),
            "PrintValueToString": (P, [P]),
            "PrintModuleToString": (P, [P]),
            "DisposeMessage": (None, [P]),
            "GetFirstGlobal": (P, [P]),
            "GetNextGlobal": (P, [P]),
            "GetFirstUse": (P, [P]),
            "GetNextUse": (P, [P]),
            "GetUser": (P, [P]),
            "IsACallInst": (P, [P]),
            "IsAInvokeInst": (P, [P]),
            "GetCalledValue": (P, [P]),
            "IsAFunction": (P, [P]),
            "GetLinkage": (U, [P]),
            "IsFunctionVarArg": (I, [P]),
            "GlobalGetValueType": (P, [P]),
            "GetNumArgOperands": (U, [P]),
            "GetArgOperand": (P, [P, U]),
            "CountParams": (U, [P]),
            "GetParam": (P, [P, U]),
            "ConstStringInContext2": (P, [P, B, S, I]),
            "ConstNamedStruct": (P, [P, PP, U]),
            "GetInitializer": (P, [P]),
            "SetInitializer": (None, [P, P]),
            "GetNumOperands": (I, [P]),
            "GetOperand": (P, [P, U]),
            "TypeOf": (P, [P]),
            "ParseIRInContext": (I, [P, P, PP, PP]),
            "GetNamedFunction": (P, [P, B]),
            "RunPasses": (P, [P, B, P, P]),
            "CreatePassBuilderOptions": (P, []),
            "DisposePassBuilderOptions": (None, [P]),
            "GetErrorMessage": (P, [P]),
            "DisposeErrorMessage": (None, [P]),
            "VerifyModule": (I, [P, I, PP]),
        }
        for name, (returns, params) in functions.items():
            fun = getattr(self.lib, "LLVM" + name)
            fun.restype, fun.argtypes = returns, params
            setattr(self, name, fun)

    def serialize(self, m):
        buf = self.WriteBitcodeToMemoryBuffer(m)
        try:
            return sha(string_at(self.GetBufferStart(buf), self.GetBufferSize(buf)))
        finally:
            self.DisposeMemoryBuffer(buf)

    def text(self, v):
        t = self.PrintValueToString(v)
        try:
            return ctypes.string_at(t).decode()
        finally:
            self.DisposeMessage(t)

    def name(self, v):
        n = c_size_t()
        p = self.GetValueName2(v, byref(n))
        return string_at(p, n.value).decode()

    def qualify(self, g):
        ui = self.GetFirstUse(g)
        v = 0
        sites = set()
        while ui:
            ins = self.GetUser(ui)
            if not (self.IsACallInst(ins) or self.IsAInvokeInst(ins)):
                return False, v, sites
            f = self.GetCalledValue(ins)
            if (
                not self.IsAFunction(f)
                or self.IsDeclaration(f)
                or self.GetLinkage(f) != 8
                or self.IsFunctionVarArg(self.GlobalGetValueType(f))
            ):
                return False, v, sites
            na = self.GetNumArgOperands(ins)
            pos = [i for i in range(na) if self.GetArgOperand(ins, i) == g]
            if na != self.CountParams(f) or pos != [na - 1]:
                return False, v, sites
            par = self.GetParam(f, na - 1)
            if self.GetFirstUse(par):
                return False, v, sites
            v += 1
            sites.add(self.name(f))
            ui = self.GetNextUse(ui)
        return v > 0, v, sites

    def wire(self, txt):
        a = self
        c = a.ContextCreate()
        bb = txt.encode()
        buf = a.CreateMemoryBufferWithMemoryRangeCopy(bb, len(bb), b"dense.ll")
        m = c_void_p()
        err = c_void_p()
        # LLVMParseIRInContext takes ownership of buf.
        try:
            rc = self.ParseIRInContext(c, buf, byref(m), byref(err))
            if rc:
                raise ValueError(ctypes.string_at(err)[:400])
            return a.serialize(m)
        finally:
            if err:
                a.DisposeMessage(err)
            if m:
                a.DisposeModule(m)
            a.ContextDispose(c)

    def independent(self, bc, src):
        a = self
        ctx = a.ContextCreate()
        buf = a.CreateMemoryBufferWithMemoryRangeCopy(bc, len(bc), b"input.bc")
        mod = c_void_p()
        try:
            assert a.ParseBitcodeInContext2(ctx, buf, byref(mod)) == 0
            data = {}
            gp = {}
            g = self.GetFirstGlobal(mod)
            while g:
                v = self.text(g)
                m = re.match(r"^@(\d+) =", v)
                if m:
                    data[m[1]] = v
                    gp[m[1]] = g
                g = self.GetNextGlobal(g)
            allowed = []
            blocked = []
            for n, t in data.items():
                m = SHAPE.fullmatch(t)
                if not m:
                    continue
                s = STR.fullmatch(data.get(m[2], ""))
                if not s:
                    continue
                rawpath = unesc(s[3])
                bb = unesc(m[3])
                assert len(bb) == 16 and int(s[2]) == len(rawpath)
                nbytes, line, col = struct.unpack("<QII", bb)
                if rawpath[:nbytes] != FILE.encode() or rawpath[nbytes:] not in (
                    b"",
                    b"\0",
                ):
                    continue
                ok, cnt, func = self.qualify(gp[n])
                if not ok:
                    blocked.append([n, line, col])
                    continue
                iv = self.GetInitializer(gp[n])
                assert self.GetNumOperands(iv) == 2
                canon = struct.pack("<QII", nbytes, 1, col)
                rv = self.ConstStringInContext2(ctx, canon, len(canon), 1)
                arr = (c_void_p * 2)(self.GetOperand(iv, 0), rv)
                self.SetInitializer(
                    gp[n], self.ConstNamedStruct(self.TypeOf(iv), arr, 2)
                )
                allowed.append([n, line, col, cnt])
            v = self.PrintModuleToString(mod)
            try:
                t = ctypes.string_at(v).decode()
            finally:
                a.DisposeMessage(v)
            d, qr = debug_key(t, src)
            key = sha(d.encode())
            return (
                dict(
                    whole_llvm_text=key,
                    whole_llvm_bitcode=self.wire(d),
                    debug=qr,
                    allowed_location_globals=len(allowed),
                    unqualified_location_globals=len(blocked),
                    allowed_location_uses=sum(x[3] for x in allowed),
                ),
                d,
            )
        finally:
            if mod:
                a.DisposeModule(mod)
            a.DisposeMemoryBuffer(buf)
            a.ContextDispose(ctx)

    def textmod(self, mod):
        v = self.PrintModuleToString(mod)
        try:
            return string_at(v).decode()
        finally:
            self.DisposeMessage(v)
