"""Check a captured standalone Ruff or AST reader ELF against its exact section and load records."""
import hashlib
import mmap
import os
import re
import shutil
import struct
import subprocess
from replay_metrics import need


def rust_main(mm, sections, crate):
    symbols = [s for s in sections if s[1] == 2]
    need(len(symbols) == 1, 'missing full symbol table')
    _, _, _, _, start, size, strid, _, _, stride = symbols[0]
    need(stride == 24 and size % stride == 0 and strid < len(sections), 'broken symbol table')
    strings = sections[strid]
    need(strings[1] == 3, 'missing symbol names')
    names = mm[strings[4]:strings[4] + strings[5]]
    pattern = rb'_RNvCs([a-zA-Z0-9]*)_' + str(len(crate)).encode() + crate.encode() + rb'4main\0'
    candidates = {m.start(): m for m in re.finditer(pattern, names)}
    found = []
    for offset, info, _, idx, _, _ in struct.iter_unpack('<IBBHQQ', mm[start:start+size]):
        if offset in candidates and info & 15 == 2 and 0 < idx < len(sections) and sections[idx][2] & 4:
            found.append(candidates[offset])
    need(len(found) == 1, ('actual defined Rust main', crate, len(found)))
    alphabet = b'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    value = 0
    for char in found[0][1]:
        value = value * 62 + alphabet.index(char)
    return {'symbol': found[0][0][:-1].decode(), 'stable_crate_id': value + (2 if found[0][1] else 1)}


def verify(z, name, observed, crate=None):
    sha = observed["whole"]
    need(re.fullmatch("[a-f0-9]{64}", sha) and name.endswith("/" + sha + ".zst")
         and 8192 < observed["size"] < (2 << 30), "invalid native witness")
    with z.open(name) as src, os.fdopen(os.memfd_create("ohm-ruff-verify"), "w+b") as body:
        proc = subprocess.Popen(["zstd", "--quiet", "--decompress", "--stdout"], stdin=subprocess.PIPE,
                                stdout=body)
        with proc.stdin as feed:
            shutil.copyfileobj(src, feed, length=1 << 20)
        need(proc.wait() == 0 and body.tell() == observed["size"], "native body decompression")
        body.seek(0)
        need(hashlib.file_digest(body, "sha256").hexdigest() == sha, "full reference bytes")
        with mmap.mmap(body.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            def digest(start, size):
                need(0 <= start <= len(mm) and 0 <= size <= len(mm) - start, "ELF extent")
                return hashlib.sha256(memoryview(mm)[start:start + size]).hexdigest()
            fields = struct.unpack_from("<16sHHIQQQIHHHHHH", mm)
            magic, form, cpu, version, _, ph, sh, _, ehsize, phsize, phnum, shsize, shnum, strid = fields
            need(magic[:7] == b"\x7fELF\x02\x01\x01" and form in (2, 3) and cpu == 62 and version == 1
                 and ehsize == 64 and phsize == 56 and shsize == 64 and strid < shnum, "ELF ABI")
            sections = list(struct.iter_unpack("<IIQQQQIIQQ", mm[sh:sh + shnum * shsize]))
            need(len(sections) == shnum, "incomplete section table")
            _, sym_type, _, _, strstart, strlen, *_ = sections[strid]
            need(sym_type == 3 and strstart + strlen <= len(mm), "section name table")
            strings = mm[strstart:strstart + strlen]
            all_sections = {}
            executable = {}
            for offset, kind, flags, _, addr, size, _, _, _, entry in sections:
                stop = strings.find(b"\0", offset)
                need(0 <= offset <= stop, "unterminated ELF name")
                key = strings[offset:stop].decode("ascii")
                desc = {"type": kind, "flags": flags, "offset": addr, "size": size, "entsize": entry,
                        "sha256": "" if kind == 8 else digest(addr, size)}
                all_sections[key] = desc
                if flags & 4:
                    executable[key] = {k: desc[k] for k in ("flags", "size", "sha256")}
            loads = []
            for typ, flags, start, addr, _, size, memsize, _ in struct.iter_unpack(
                    "<IIQQQQQQ", mm[ph:ph + phnum * phsize]):
                if typ == 1 and flags & 1:
                    loads.append({"flags": flags, "offset": start, "addr": addr, "filesz": size,
                                  "memsz": memsize, "sha256": digest(start, size)})
            need(all_sections == observed["sections"] and executable == observed["executable"] and
                 loads == observed["loads"] and ".text" in executable and loads,
                 "independent sections or ELF program loads")
            result = {"whole": sha, "bytes": observed["size"], "sections": len(all_sections),
                      "executable_sections": len(executable), "executable_loads": len(loads)}
            if crate:
                result['rust_main'] = rust_main(mm, sections, crate)
            return result
