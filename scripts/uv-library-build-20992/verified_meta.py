"""Compare native metadata with its original typed writer when only opaque-lifetime ordinals move."""
from pathlib import Path
from functools import lru_cache
import hashlib
import inspect
import json
import os
import runpy
import struct
import subprocess
import tarfile
import tempfile
import types

import native
import archive_wire as wire

HERE=Path(__file__).resolve().parent
manifest=json.loads((HERE/"metadata-files.json").read_bytes())
def kit():
    root=native.TRANSIENT/"metadata-kit"
    package=HERE/"metadata-kit.tar.xz"
    assert native.sha(package)==manifest["kit_sha"]=="37cbdfdc33b3f645ea68bf3595f6aa19716f2cbfba03baa98e9a5ad1a58bd176"
    if not root.exists():
        root.mkdir()
        with tarfile.open(package)as tar:
            entries=tar.getmembers();assert len(entries)==len(manifest["toolkit"])==len({x.name for x in entries})
            for x in entries:
                assert x.isfile() and x.name in manifest["toolkit"] and ".." not in Path(x.name).parts and not Path(x.name).is_absolute()
                dst=root/x.name;dst.parent.mkdir(parents=True,exist_ok=True);data=tar.extractfile(x).read();assert wire.ident(data)==manifest["toolkit"][x.name];dst.write_bytes(data)
    assert all(native.sha(root/p)==h for p,h in manifest["toolkit"].items())
    return runpy.run_path(str(root/manifest["kit_module"]))
@lru_cache(1)
def decoder():
    tools=kit();original=tools["L"]["project"];src=inspect.getsource(original)
    point='        table=t[name]\n        for j in idx:'
    assert src.count(point)==1
    src=src.replace(point,'        table=t[name]\n        if table["sparse"]:\n            emit(table["position"], bitmap_rows(warm, table, order), name + " sparse bitmap, prefix and packed rows")\n            continue\n        for j in idx:')
    start=src.index('    new={key:j for j,key in enumerate(u)}');end=src.index('    require(bytes(dst)==cold',start)
    src=src[:start]+'''    source_map = typed_map(v)
    require(source_map == area, "entire source physical ODHT must be reproduced")
    projected_map = typed_map(u)
    require(len(projected_map) == length, "changed physical ODHT length")
    emit(start, projected_map, "complete native ODHT keys, indices and collision control bytes")
'''+src[end:]
    scope=dict(original.__globals__,bitmap_rows=bitmap_rows,typed_map=tools["ODHT"]["def_path_hash_map"]);exec(compile(src,"<enrolled-sparse-lifetime-writer>","exec"),scope)
    return tools,scope["project"]


def native_header(data):
    driver=native.sha(next((native.SDK/"lib").glob("librustc_driver*.so")))
    dest=native.ROOT/"native-headers"/driver;dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=native.TRANSIENT)as tmp:
        p=Path(tmp)/"lib.rmeta";p.write_bytes(data);argv=[str(native.SDK/"bin/rustc"),"-Zls=root",str(p)]
        h=subprocess.run(argv,env=native.environment(),capture_output=True,timeout=30,check=True)
        assert h.stdout and not h.stderr
    path=dest/(wire.ident(data)+".zls-root")
    if path.exists():assert path.read_bytes()==h.stdout
    else:path.write_bytes(h.stdout);native.save(path.with_suffix(".json"),dict(argv=argv,raw_rmeta=wire.ident(data),exit=h.returncode,stdout=wire.ident(h.stdout),native_driver=driver))
    return h.stdout

def semantic(a,b,crate):
    tools,project=decoder();reader=tools["check_delta"]
    inputs={wire.ident(v):v for v in (a,b)}
    def exact(pair):
        v=inputs[pair[1]];assert len(v)==pair[0] and wire.ident(v)==pair[1];return v
    env=dict(reader.__globals__,C=dict(reader.__globals__["C"],raw=exact))
    bound=types.FunctionType(reader.__code__,env,reader.__name__,reader.__defaults__,reader.__closure__)
    got=bound([len(a),wire.ident(a)],[len(b),wire.ident(b)],crate)
    assert all(got["checks"].values()) and set(got["physical_moved"])=={"OpaqueLifetime"}
    projected=project(a,b);assert projected["check_sha256"]==wire.ident(b) and projected["different_bytes"]==sum(x!=y for x,y in zip(a,b))
    paths=[native_header(x)for x in (a,b)]
    assert paths[0]==paths[1];positions={"span":projected["span_span"][0]+1,"local-rdr":tools["C"]["Z"]["ROOT"](a)["tables"]["rdr_hashes.local"]["values_position"]+3,"unrelated-header":len(b)-17}
    refused={}
    for name,pos in positions.items():
        broken=bytearray(b);broken[pos]^=1
        try:project(a,bytes(broken))
        except (ValueError,AssertionError,IndexError,KeyError)as e:refused[name]=[pos,type(e).__name__]
        else:raise ValueError("accepted damaged "+name)
    return {"native_root_header_sha256":wire.ident(paths[0]),"typed":got,"all_input_bytes_reconstructed":projected,"hostile_rejections":refused}


def bitmap_rows(data, table, order):
    length, width = table["length"], table["width"]
    nblocks = (length + 63) // 64
    start, values, end = table["position"], table["values_position"], table["end"]
    assert table["sparse"] and values - start == nblocks * 12 and 0 < width <= 32
    old = []
    cursor = values
    for block in range(nblocks):
        mask, prefix = struct.unpack_from("<QI", data, start + block * 12)
        assert prefix == (cursor - values) // width
        proper = min(64, length - 64 * block)
        assert mask >> proper == 0
        for bit in range(proper):
            if mask & (1 << bit):
                row = data[cursor:cursor + width]
                assert len(row) == width and any(row)
                old.append(row)
                cursor += width
            else:
                old.append(None)
    assert cursor == end and len(old) == length
    def wire(physical_order):
        indexes, stored = bytearray(), bytearray()
        for b in range(nblocks):
            prefix = len(stored) // width
            mask = 0
            for bit, i in enumerate(physical_order[b * 64:(b + 1) * 64]):
                if old[i] is not None:
                    mask |= 1 << bit
                    stored.extend(old[i])
            indexes.extend(struct.pack("<QI", mask, prefix))
        return indexes + stored
    assert wire(list(range(length))) == data[start:end]
    assert sorted(order) == list(range(length))
    result = wire(order)
    assert len(result) == end - start
    return result

def metadata_member(raw):
    roles = wire.archive(raw)
    member, = (v for v in roles if v[0] == "lib.rmeta")
    elf = member[2]
    assert elf[:7] == b"\x7fELF\x02\x01\x01"
    section_table = struct.unpack_from("<Q", elf, 40)[0]
    width, count, name_index = struct.unpack_from("<HHH", elf, 58)
    assert width == 64 and 0 < name_index < count <= 256
    sections = [struct.unpack_from("<IIQQQQIIQQ", elf, section_table + i * width) for i in range(count)]
    name_data = sections[name_index]
    names = elf[name_data[4]:name_data[4] + name_data[5]]
    rmeta, = (row for row in sections if names[row[0]:].split(b"\0", 1)[0] == b".rmeta")
    offset, size = rmeta[4:6]
    assert rmeta[1] == 1 and offset + size <= len(elf)
    contents = elf[offset:offset + size]
    assert contents.startswith(b"rust\0")
    return member[1] + offset, contents, elf
