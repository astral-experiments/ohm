"""Re-read original instruments, typed records, binutils results and exact ELF/object bytes."""
import collections
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import zipfile

PHASES=['00-empty-original','01-settled-original','02-ordinary','03-ordinary-repeat','04-forced-root','05-forced-rebundle','06-independent-empty','07-repair','08-clean-repair']
TARGET='aarch64-unknown-linux-gnu'
def digest(b):return hashlib.sha256(b).hexdigest()
def expected(m):return 29 if m in ('replace-same-mtime','higher-priority') else None
def extract_archive(b):
    assert b.startswith(b'!<arch>\n')
    off=8;long=b'';out={}
    while off<len(b):
        h=b[off:off+60];assert len(h)==60 and h[58:]==b'`\n'
        n=h[:16].decode('ascii').rstrip();size=int(h[48:58]);data=b[off+60:off+60+size];assert len(data)==size
        off+=60+size+(size%2)
        if n=='//':long=data;continue
        if n in ('/','/SYM64/','__.SYMDEF','__.SYMDEF SORTED'):continue
        if n.startswith('#1/'):
            nl=int(n[3:]);n=data[:nl].rstrip(b'\0').decode();data=data[nl:]
        elif n.startswith('/') and n[1:].isdigit():
            n=long[int(n[1:]):].split(b'/\n',1)[0].decode()
        else:n=n.removesuffix('/')
        assert n and n not in out,(n,list(out));out[n]=data
    return out

def inspect(z,role):
    names=set(z.namelist())
    def read(n):return json.loads(z.read(n))
    # All saved memory objects have a physical SHA from the original bytes.
    objs={Path(n).stem:n for n in names if n.startswith('objects/') and n.endswith('.gz')}
    for h,n in objs.items():assert digest(gzip.decompress(z.read(n)))==h
    def obj(h):
        d=gzip.decompress(z.read(objs[h]));assert digest(d)==h;return d
    sdk=read('sdk.json');assert sdk['role']==role and len(sdk['files'])==119
    driver=sdk['files'][sdk['driver_path']];assert driver[0]==('d38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084' if role=='P' else '45d8737f938d6ed97be5903342718f087d0af6ea710dd3c2416babc8c570d4b7')
    infos={}; native_cmds=collections.Counter(); cases=[];adverse=[]
    for fn in sorted(n for n in names if n.endswith('/result.json')):
        kind,m,phase,_=fn.split('/');case=f'{kind}/{m}';base=case+'/'+phase+'/';r=read(fn)
        assert digest(gzip.decompress(z.read(base+'stdout.gz')))==r['stdout']
        assert digest(gzip.decompress(z.read(base+'stderr.gz')))==r['stderr']
        lines=[json.loads(l) for l in gzip.decompress(z.read(base+'stdout.gz')).splitlines() if l.strip()]
        finished,=[x for x in lines if x['reason']=='build-finished']
        assert finished['success']==(r['cargo_exit']==0)
        assert r['typed']==[[x['target']['name'],x['target']['kind'],x['fresh'],x['filenames']] for x in lines if x['reason']=='compiler-artifact']
        if r['cargo_exit']==0:
            assert r['value'] and isinstance(r['value']['value'],int)
            elf=obj(r['value']['sha256']);assert elf[:6]==b'\x7fELF\x02\x01' and elf[18:20]==b'\xb7\x00'
            assert obj(r['value']['qemu_stdout'])==str(r['value']['value']).encode()+b'\n' and not obj(r['value']['qemu_stderr'])
            val=r['value']['value']; assert val in (17,29)
        else:
            assert r['cargo_exit']==101 and r['value'] is None;val=None
            assert 'qa_owned_atomic' in (gzip.decompress(z.read(base+'stderr.gz'))+gzip.decompress(z.read(base+'stdout.gz'))).decode(errors='replace')
        native=r['native'];raw=z.read(base+'kernel.tar.gz');assert digest(raw)==r['kernel_tar']
        observed_pids={}; events=collections.defaultdict(list);original={}
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            for f in t.getmembers():
                b=t.extractfile(f).read();original[f.name]=digest(b);pid=int(f.name.split('.')[-1])
                for l in b.decode(errors='replace').splitlines():
                    if l.startswith('execve(') and l.endswith('= 0'):
                        dec=json.JSONDecoder();exe,k=dec.raw_decode(l[7:]);argv,_=dec.raw_decode(l[7+k:].removeprefix(', ').lstrip())
                        events[pid].append((exe,argv))
                    if re.search(r'^(open(at|at2)?|newfstatat|statx|access)\(',l) and 'libqa_owned_atomic.a' in l:
                        observed_pids.setdefault(pid,[]).append(l)
        assert native['thread_files']==original
        assert {p:v for p,v in events.items()}=={p:[(e['exe'],e['argv']) for e in native['execs'] if e['pid']==p] for p in {e['pid'] for e in native['execs']}}
        assert observed_pids=={e['pid']:e['calls'] for e in native['opened']}
        crates=[]
        for pid,k,crate in r['rustc']:
            path,av=next((ep,a) for ep,a in events[pid] if Path(ep).name=='rustc' and (
                (k=='link-only' and any(v.startswith('-Zlink-only') for v in a)) or (k=='full' and '--crate-name' in a and a[a.index('--crate-name')+1]==crate)))
            assert '/toolchains/ohm/bin/rustc' in path or '/subject/bin/rustc' in path,path
            crates.append(k+':'+str(crate))
        for pid in r['cross_linker_pids']:
            assert any(Path(ep).name in ('ld','ld.bfd','ld.lld','aarch64-linux-gnu-ld','aarch64-linux-gnu-ld.bfd') and ('aarch64' in ep or any('aarch64' in v for v in av)) for ep,av in events[pid])
        provenance=[]
        providers=read(case+'/provision/products.json');native_objects={k:obj(v) for k,v in providers['objects'].items()}
        for lib,a in r['libs'].items():
            members=extract_archive(obj(a['sha256']));assert len(members)==len(a['members'])
            for x in a['members']:
                blob=members[x['name']];assert (len(blob),digest(blob))==(x['length'],x['sha256'])
                actually=sorted(h for h,data in native_objects.items() if data in blob)
                assert sorted(x['matches_provider_object'])==actually
                if lib=='qa_plain':provenance+=actually
        infos[(kind,m,phase)]={'code':r['cargo_exit'],'value':val,'elf':r['value'] and r['value']['sha256'],'crates':crates,'linkers':len(r['cross_linker_pids']),'embedded_B':provenance}
        native_cmds.update(crates)
    for kind,m in sorted({(k,m) for k,m,_ in infos}):
        rows={phase:infos[kind,m,phase] for phase in PHASES if (kind,m,phase) in infos};path=kind+'/'+m+'/'
        if '00-empty-original' in rows and path+'baseline.json' in names:
            b=read(path+'baseline.json'); assert re.search(rb'\bldar\s+x[0-9]+,\s*\[x[0-9]+\]',obj(b['original_leaf_disassembly']))
            assert any('R_AARCH64_' in a and 'qa_owned_word' in a for a in b['rooted_relocations'])
            assert b['bundle_original_objects']==(['17'] if kind.startswith('bundled') else [])
        if path+'complete.json' not in names:
            cases.append({'kind':kind,'mutation':m,'complete':False,'phases':rows});continue
        assert set(rows)==set(PHASES) and rows[PHASES[0]]['value']==rows[PHASES[1]]['value']==17
        model=expected(m);base=read(path+'mutation.json')
        assert base['expected']==model and read(path+'c-reference-mutated.json')['answer']==model
        if m=='replace-same-mtime':
            old,new=base['before'],base['after_late'];assert all(old[k]==new[k] for k in ('dev','ino','mtime_ns','size')) and old['sha256']!=new['sha256']
        assert rows['05-forced-rebundle']['value']==rows['06-independent-empty']['value']==model
        assert 'full:qa_plain' in rows['05-forced-rebundle']['crates'] and rows['08-clean-repair']['value']==17
        divergent=[]
        for phase in ('02-ordinary','03-ordinary-repeat','04-forced-root','07-repair'):
            if rows[phase]['value']!=(17 if phase=='07-repair' else model):
                divergent.append(phase)
                if phase in ('02-ordinary','03-ordinary-repeat','07-repair'):
                    adverse.append([kind,m,phase,rows[phase]['code'],rows[phase]['value'],17 if phase=='07-repair' else model])
        cases.append({'kind':kind,'mutation':m,'complete':True,'expected':model,'divergent':divergent,'phases':rows})
    terminal='terminal.json' in names
    if terminal:assert len(cases)==sum(c['complete'] for c in cases)==12 and len(infos)==108
    return {'role':role,'compiler':sdk['source'],'driver':driver,'cargo':sdk['files']['bin/cargo'],'file_objects':len(objs),'terminal':terminal,'visits':len(infos),'cases':cases,'divergences_from_empty':adverse,'full_roster_counts':dict(native_cmds)}
