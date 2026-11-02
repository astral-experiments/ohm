"""Run two authentic signed SDKs serially on the same worker, using fresh identical logical paths."""
import argparse
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import census


def save(path, data):
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    with path.open("xb") as f:
        f.write(gzip.compress(encoded, mtime=0))


def h(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data, ranges, start=0, end=None):
    end = len(data) if end is None else end
    dig = hashlib.sha256()
    left = start
    for a, b in sorted(ranges):
        a, b = max(start, a), min(end, b)
        if a >= b:
            continue
        assert left <= a
        dig.update(data[left:a])
        dig.update(bytes(b-a))
        left = b
    dig.update(data[left:end])
    return dig.hexdigest()


def elf(data):
    """Retain every ELF byte through the raw hash, plus exact section and segment comparisons."""
    assert bytes(data[:6]) == b"\x7fELF\x02\x01" and struct.unpack_from("<H",data,18)[0] == 62
    phoff, shoff = struct.unpack_from("<QQ",data,32)
    phsize, phnum, shsize, shnum, shstr = struct.unpack_from("<5H",data,54)
    assert phsize == 56 and shsize == 64 and 0 < shstr < shnum
    assert phoff + phsize*phnum <= len(data) and shoff + shsize*shnum <= len(data)
    def sh(i):
        return struct.unpack_from("<IIQQQQIIQQ",data,shoff+i*shsize)
    strings = sh(shstr)
    table = bytes(data[strings[4]:strings[4]+strings[5]])
    sections = {}
    fields = []
    ids = []
    for i in range(shnum):
        label, kind, flags, addr, at, size, link, info, align, entsize = sh(i)
        name = table[label:table.index(0, label)].decode("utf-8")
        assert name not in sections and (kind == 8 or at + size <= len(data))
        sections[name] = [kind, flags, addr, at, size, link, info, align, entsize,
                          None if kind == 8 else h(data[at:at+size])]
        if name == ".rodata":
            fields.append([shoff+i*shsize+56, shoff+i*shsize+64])
        if kind == 7:
            cursor = at
            while cursor+12 <= at+size:
                n, desc, typ = struct.unpack_from("<III",data,cursor)
                key = bytes(data[cursor+12:cursor+12+n])
                body = cursor+12+((n+3)&~3)
                assert body+desc <= at+size
                if key == b"GNU\0" and typ == 3:
                    ids.append([body,body+desc])
                cursor = body+((desc+3)&~3)
    assert ".text" in sections and len(ids) <= 1 and len(fields) <= 1
    loads = []
    for i in range(phnum):
        kind, flags, off, vaddr, _, size, mem, align = struct.unpack_from("<IIQQQQQQ",data,phoff+i*phsize)
        if kind == 1:
            assert off+size <= len(data)
            loads.append([flags,off,vaddr,size,mem,align,h(data[off:off+size]),normalized(data,ids,off,off+size)])
    return {"bytes":len(data),"sha256":h(data),"sections":sections,"loads":loads,
            "build_id":bytes(data[slice(*ids[0])]).hex() if ids else None,
            "rodata_entsize":sections[".rodata"][8] if fields else None,
            "normalized_build_id_and_rodata_entsize":normalized(data,ids+fields)}


def observe(source, work, folder):
    rows = [json.loads(v) for v in (folder/"stdout.jsonl").read_bytes().splitlines()]
    units, files, aliases = {}, {}, {}
    for a in rows:
        if a["reason"] != "compiler-artifact":
            continue
        t = a["target"]
        key = "|".join([a["package_id"],t["name"],",".join(t["kind"]),str(a["profile"]["test"]),
                        t["src_path"],",".join(sorted(a["features"])),",".join(sorted(a["filenames"]))])
        assert key not in units
        units[key] = {"fresh":a["fresh"],"executable":a["executable"],"files":a["filenames"]}
        for raw in a["filenames"]:
            p = Path(raw)
            s = p.stat()
            assert p.resolve().is_relative_to(work)
            ident = (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            if ident in aliases:
                files[raw] = {"alias":aliases[ident], "stat":ident}
                continue
            aliases[ident] = raw
            with p.open("rb") as f:
                header = f.read(20)
                if header[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H",header,16)[0] in (2,3):
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                        with memoryview(m) as data:
                            record = elf(data)
                else:
                    f.seek(0)
                    record = {"bytes":s.st_size,"sha256":hashlib.file_digest(f,"sha256").hexdigest()}
            record["stat"] = ident
            files[raw] = record
    assert any(".so" in p and "sections" in r for p,r in files.items())
    save(folder/"product-bytes.json.gz",{"units":units,"files":files})
    fingerprint = {}
    for base in (work/"target",work/"build"):
        for p in base.rglob("*"):
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 2**20:
                continue
            if p.parent.name not in {"fingerprint",".fingerprint"} and ".fingerprint" not in p.parts:
                continue
            if p.suffix == ".json" or p.name.startswith("dep-"):
                b = p.read_bytes()
                marker = sorted(set(m.decode() for m in re.findall(rb"ohm-(?:recheck-dependent-links(?:-v2)?|untracked-relink-inputs|foreign-span-bytes)",b)))
                fingerprint[str(p.relative_to(work))] = {"sha256":h(b),"markers":marker}
                if p.suffix == ".json":
                    try:
                        fingerprint[str(p.relative_to(work))]["contents"] = json.loads(b)
                    except (UnicodeDecodeError,ValueError):
                        pass
                elif marker:
                    fingerprint[str(p.relative_to(work))]["translated_depinfo_hex"] = b.hex()
    save(folder/"cargo-fingerprints.json.gz",fingerprint)


def role_spec(release):
    if release == "18":
        return json.loads((HERE/"signed-18.json").read_bytes())
    return json.loads((HERE.parent/"ruff-default-owner-pmu/signed-sdk.json").read_bytes())


def carry(role):
    work, evidence, _ = census.paths()
    destination = work.parent/"matched-ruff-workspace-census"/role
    destination.parent.mkdir(exist_ok=True)
    assert not destination.exists() and not work.exists()
    if role == "22":
        first = destination.parent/"18"/"evidence"/"qualified.json"
        assert first.is_file()
    census.install("ohm-1.99.0-"+role)


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("verb",choices=("install","run"))
    arg.add_argument("role",choices=("18","22"))
    arg.add_argument("source",type=Path)
    args = arg.parse_args()
    role = args.role
    census.common.SDK = role_spec(role)
    work, evidence, sdk = census.paths()
    tag = "ohm-1.99.0-"+role
    if args.verb == "install":
        return carry(role)
    assert census.git(args.source,"rev-parse","HEAD^{tree}") == "62d3f106c5e41f6022847f26ff8c7dc00139f7b1"
    ident = json.loads((evidence/"identity.json").read_bytes())
    assert ident["sdk"] == census.acquire.verify_sdk(sdk)
    assert all(not (work/n).exists() for n in ("home","cargo","build","target"))
    census.study(args.source.resolve(strict=True),tag,observe)
    assert ident["sdk"] == census.acquire.verify_sdk(sdk)
    target = work.parent/"matched-ruff-workspace-census"/role
    assert not target.exists()
    os.rename(work,target)
    if role == "22":
        first = json.loads((target.parent/"18/evidence/identity.json").read_bytes())
        assert all(ident[k] == first[k] for k in ("run","sha","boot","worker","ruff","lock"))
        assert ident["release_asset"] != first["release_asset"]
    print(f"source-matched signed {role} complete on {ident['boot']}",flush=True)

if __name__ == "__main__":
    main()
