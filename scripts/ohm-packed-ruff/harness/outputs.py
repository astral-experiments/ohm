"""Read actual rlib members and check native and contradictory Rust consumers."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re

import omission as om


INCR_MEMBER = re.compile(r"([A-Za-z0-9_]+-[0-9a-f]{16}\.[a-z0-9]{25})\.([a-z0-9]{7})(\.rcgu\.o)")


def stable_member(name):
    match = INCR_MEMBER.fullmatch(name)
    return match[1] + ".0000000" + match[3] if match else name


def canonical(entry):
    """Preserve the raw index. Project only verified embedded incremental session salts."""
    members={}
    replacements={}
    for name, record in entry["members"].items():
        stable=stable_member(name)
        if stable!=name:
            assert record[0]=="elf"
            replacements[name.encode()]=stable.encode()
        assert stable not in members, ("CGU name collision",name,stable)
        members[stable]=record
    if "lib.rmeta-link" in members:
        original=base64.b64decode(entry["raw_link_metadata"],validate=True)
        assert len(original)==members["lib.rmeta-link"][1]
        assert hashlib.sha256(original).hexdigest()==members["lib.rmeta-link"][2]
        projected=original
        for old,new in replacements.items():
            # The exact compiler encodes each CGU’s archive member name in this index.
            assert projected.count(old)==1,("late-link metadata lacks unique matching CGU",old)
            projected=projected.replace(old,new)
        members["lib.rmeta-link"]=["link_metadata",len(projected),hashlib.sha256(projected).hexdigest()]
    return members


def ar_index(path):
    data=path.read_bytes()
    om.require(data.startswith(b"!<arch>\n"),path)
    pos=8;names=b"";records={};extra={}
    while pos<len(data):
        h=data[pos:pos+60]
        om.require(len(h)==60 and h[-2:]==b"`\n",("malformed ar",path,pos))
        n=int(h[48:58]);s=pos+60;t=s+n;om.require(t<=len(data),("truncated ar",path))
        tag=h[:16].rstrip();payload=memoryview(data)[s:t];pos=t+n%2
        if tag==b"//":names=bytes(payload);continue
        if tag in (b"/",b"/SYM64/"):continue
        if tag.startswith(b"#1/"):
            size=int(tag[3:]);name=bytes(payload[:size]).rstrip(b"\0").decode();payload=payload[size:]
        elif tag.startswith(b"/") and tag[1:].isdigit():
            ix=int(tag[1:]);end=names.index(b"/\n",ix);name=names[ix:end].decode()
        else:name=tag.rstrip(b"/").decode()
        om.require(name not in records,("duplicate archive member",path,name))
        kind="metadata" if name.endswith(".rmeta") else "elf" if payload[:4]==b"\x7fELF" else "other"
        records[name]=[kind,len(payload),hashlib.sha256(payload).hexdigest()]
        if name=="lib.rmeta-link":extra["raw_link_metadata"]=base64.b64encode(payload).decode()
    om.require(pos==len(data),("bad ar boundary",path))
    return {"archive":hashlib.sha256(data).hexdigest(),"members":records,**extra}


def native_execs(path, sdk):
    last={};started=[];pending={};cargo=0;wild=0
    for line in path.read_text().splitlines():
        done=re.match(r'^(\d+)\s+<\.\.\. execve resumed>\)\s+= ([-\d]+)',line)
        if done:
            process=pending.pop(done[1],None)
            if process and done[2]=="0":started.append(process)
            continue
        call=re.match(r'^(\d+)\s+execve\(("(?:\\.|[^"])+"), (\[.*\]), ',line)
        if not call:continue
        file=Path(ast.literal_eval(call[2]))
        if not file.is_file():continue
        role=None
        for label,known in (("rustc",sdk/"bin/rustc"),("cargo",sdk/"bin/cargo"),("wild",sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")):
            if file.samefile(known):role=label;break
        if role is None:continue
        record=(int(call[1]),role,ast.literal_eval(call[3]))
        if line.endswith("= 0"):started.append(record)
        elif line.endswith("<unfinished ...>"):pending[call[1]]=record
    assert not pending
    actual=[]
    for pid,role,argv in started:
        if role=="cargo":cargo+=1
        elif role=="wild":wild+=1
        elif "--crate-name" in argv:actual.append({"pid":pid,"crate":argv[argv.index("--crate-name")+1],"argv":argv})
    assert cargo==1,(cargo,len(started))
    return {"real_cargo":cargo,"wild":wild,"rustcs":actual}


def outputs(messages, phase_root, root, base, env, source, state, run):
    targets=[m for m in messages if m['reason']=='compiler-artifact']
    externs=[];indices={};foreign={}
    for unit in targets:
        name=unit['target']['name']
        if not ("lib" in unit["target"]["kind"] and name in ("ruff_python_ast","ruff_python_parser")):
            continue
        lib,=[Path(f) for f in unit["filenames"] if f.endswith(".rlib")]
        externs+=["--extern",f"{name}={lib}"]
    assert len(externs)==4
    for lib in sorted({Path(f) for unit in targets for f in unit["filenames"] if f.endswith(".rlib")}):
        # A disambiguated archive filename identifies each Cargo compilation unit.
        assert lib.name not in indices
        indices[lib.name]=ar_index(lib)
    om.publish(phase_root/"archive-index.json.gz",indices)
    dirs={Path(f).parent for t in targets for f in t['filenames']}
    for n in om.ROOT_NAMES:
        for pat in ("*.rlib","*.so"):dirs.update(f.parent for f in (root/n).rglob(pat))
    flags=externs[:]
    for d in sorted(dirs):flags+=["-L","dependency="+str(d)]
    for d in sorted({m['out_dir'] for m in messages if m.get('out_dir')}):flags+=["-L","native="+str(d)]
    oracle=base/"reader-work";oracle.mkdir(exist_ok=True)
    read=oracle/"reader"
    run(["rustc","+ohm","--edition=2024","--crate-name","ohm_branch_reader",base/"harness/consumer.rs",*flags,"-o",read],
        source,env,phase_root/"link-reader",0)
    expected=64 if state=="A" else 56
    p=run([read],source,env,phase_root/"read-native",0)
    assert p.stdout.decode().strip()==f"Expr={expected} valid=1 rejected"
    # The metadata oracle exercises both the correct and contradictory view of this same archive.
    for layout in (64,56):
        f=oracle/"layout.rs"
        f.write_text(f"use ruff_python_ast::Expr;\nconst _: [(); {layout}] = [(); std::mem::size_of::<Expr>()];\n"
                     'pub fn parse() { let _ = ruff_python_parser::parse_module("x = 1"); }\n')
        q=run(["rustc","+ohm","--edition=2024","--crate-type=lib","--emit=metadata","--error-format=json",
               f,*flags,"-o",oracle/"layout.rmeta"],source,env,phase_root/f"layout-{layout}",int(expected!=layout))
        if expected!=layout:assert any(m.get("code") and m["code"]["code"]=="E0308" for m in map(json.loads,q.stderr.splitlines()))
    return {"reader_sha256":om.sha(read),"typed_size":expected,"archives":indices}


def compare(fresh, observed):
    assert observed["reader_sha256"]==fresh["reader_sha256"] and observed["typed_size"]==fresh["typed_size"]
    assert set(observed["archives"])==set(fresh["archives"])
    differences={}
    for lib,entry in observed["archives"].items():
        actual=canonical(entry);other=canonical(fresh["archives"][lib])
        assert set(actual)==set(other),("canonical archive member namespace changed",lib)
        changed=[name for name,value in actual.items() if value!=other[name]]
        if changed:differences[lib]=changed
    return differences
