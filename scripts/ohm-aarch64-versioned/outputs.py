"""Bind the emitted native jobs, raw binary depfiles, and target ELF of a normal Cargo build."""
from pathlib import Path
import ast
import gzip
import hashlib
import json
import re
import subprocess
import shutil
import tarfile
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
from native_link_kinds import kind,RE
from hashlib import sha256 as H

def execs(path,sdk):
    result=[]
    with tarfile.open(path) as arc:
        for f in arc:
            if not f.isfile():continue
            body=arc.extractfile(f).read()
            for row in body.splitlines():
                if not row.startswith((b'execve(',b'execveat(')) or not row.endswith(b'= 0'):continue
                m=RE.fullmatch(row);assert m,row[:200]
                exe,argv=(ast.literal_eval(v.decode()) for v in m.groups())
                entry={'pid':int(f.name.rsplit('.',1)[1]),'executable':exe,'argv':argv,'raw_process':H(body).hexdigest()}
                if exe==str(sdk/'bin/rustc'):
                    entry['kind'],entry['target'],entry['input']=kind(argv)
                    if '--crate-name' in argv:entry['crate']=argv[argv.index('--crate-name')+1]
                elif exe==str(sdk/'bin/cargo'):entry['kind']='cargo'
                elif re.search(r'/(?:aarch64-linux-gnu-)?(?:ld|ld.bfd|ld.lld)$',exe):entry['kind']='ld'
                elif exe.endswith('/collect2'):entry['kind']='collect2'
                elif exe.endswith('/aarch64-linux-gnu-gcc'):entry['kind']='gcc'
                else:entry['kind']='other'
                result.append(entry)
    return result

def one_cargo(events,cli):
    dispatch=[x for x in events if x['kind']=='cargo']
    assert len(dispatch)==1 and dispatch[0]['argv'][1:]==cli[2:],dispatch

def encoded_file(body):
    at=0
    def take(n):
        nonlocal at
        assert 0<=n<=len(body)-at
        part=body[at:at+n];at+=n
        return part
    def integer(n):return int.from_bytes(take(n),'little')
    def string():return os.fsdecode(take(integer(4)))
    import os
    integer(4);assert integer(1)==255
    version=integer(1);assert version in (2,4)
    files=[]
    for _ in range(integer(4)):
        kind=integer(1);assert kind in (0,1);name=string();cs=integer(1);assert cs in (0,1)
        if cs:integer(8);string()
        files.append((kind,name,cs))
    for _ in range(integer(4)):
        string();exists=integer(1);assert exists in (0,1)
        if exists:string()
    index=None
    if body[at:at+4]==b'LNK1':
        take(4);index=integer(4);assert index<len(files)
        digest=subprocess.check_output(['b3sum'],input=body[:at]).decode().split()[0]
        assert bytes.fromhex(digest)==take(32)
        assert files[index][0]==1 and files[index][2]==0 and files[index][1] in ('/dev/null/ohm-recheck-dependent-links','/dev/null/ohm-recheck-dependent-links-v2')
    if at<len(body):
        assert take(4)==b'OBS1';i=integer(4);assert i<len(files);assert integer(1)==0
        digest=subprocess.check_output(['b3sum'],input=body[:at]).decode().split()[0]
        assert bytes.fromhex(digest)==take(32)
    assert at==len(body)
    return {'has_LNK1':index is not None,'linked_marker':files[index][1] if index is not None else None,
            'marker_v2':any('/dev/null/ohm-recheck-dependent-links-v2'==v[1] for v in files),
            'ordinary_or_synthetic_markers':[v[1] for v in files if '/dev/null/ohm-' in v[1]],'version':version}

def read_files(dest, roots, crate):
    # Read the real raw .d and Cargo's binary dep-* separately, preserving each content before the next command.
    result={};store=dest/'actual-files';store.mkdir()
    seen=set()
    for root in roots:
        for p in root.rglob('*'):
            normalized=crate.replace('-','_')
            is_raw=(p.name.startswith(normalized+'-') or p.name==normalized+'.d') and p.suffix=='.d'
            encoded=p.name in ('dep-lib-'+normalized,'dep-bin-'+normalized,'dep-bin-'+crate)
            if not (is_raw or encoded) or not p.is_file(): continue
            st=p.stat();ident=(st.st_dev,st.st_ino);raw=p.read_bytes()
            if ident in seen:continue
            seen.add(ident);key=H(raw).hexdigest();out=store/key
            if not out.exists():out.write_bytes(raw)
            info={'name':str(p),'sha256':key,'kind':'depfile' if is_raw else 'encoded','len':len(raw),'ino':st.st_ino,'dev':st.st_dev}
            if is_raw:
                rules=[x for x in raw.decode().splitlines() if ': ' in x]
                first=rules[0].split(': ',1)[1].split();own=[x for x in rules if x.split(': ',1)[0]==str(p)]
                if not own:own=[x for x in rules if x.split(': ',1)[0].endswith('/'+p.name)]
                if not own:
                    assert len(rules)==1 and not any(line.endswith(b':') for line in raw.splitlines()),(p,rules)
                    info.update(kind='cargo-exported-depfile',first=[v for v in first if '/dev/null/ohm-' in v])
                    result[str(p)]=info
                    continue
                assert len(own)==1,(p,rules)
                ordinary=own[0].split(': ',1)[1].split()
                markers=lambda x:[f for f in x if '/dev/null/ohm-' in f]
                info.update(first=markers(first),ordinary=markers(ordinary),fake=[x[:-1] for x in raw.decode().splitlines() if x.startswith('/dev/null/ohm-') and x.endswith(':')])
            else:
                info.update(encoded_file(raw))
            result[str(p)]=info
    assert any(v['kind']=='depfile' for v in result.values()),(roots,crate)
    return result

def opened_depfiles(trace, paths):
    wanted={str(p): ('"'+str(p)+'"').encode() for p in paths}
    found=set()
    with tarfile.open(trace) as t:
        for f in t:
            if not f.isfile():continue
            for ln in t.extractfile(f).read().splitlines():
                if b'openat(' not in ln or not re.search(rb'= [0-9]+$',ln):continue
                for name,exact in wanted.items():
                    if exact in ln:found.add(name)
    return sorted(found)
