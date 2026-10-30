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
ROLES={'upstream':12,'signed-off':12,'signed-on':6,'strict-P':8,'strict-C':8}

PHASES=['00-empty-original','01-settled-original','02-ordinary','03-ordinary-repeat','04-forced-root','05-forced-rebundle','06-independent-empty','07-repair','08-clean-repair']
TARGET='aarch64-unknown-linux-gnu'
def digest(b):return hashlib.sha256(b).hexdigest()
def expected(m):return 29 if m in ('replace-same-mtime','higher-priority','normal-replacement') else None
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
    sdk=read('sdk.json');assert sdk['role']==role
    tools=read('tools.json') if 'tools.json' in names else None
    n=len(sdk['files']);driver=sdk['files'][sdk['driver_path']]; cargo=sdk['files']['bin/cargo'][0]
    if role=='upstream':
        assert n>40 and 'b940084d7eb6a299eb4bfeb8e34901bc051e7ac4' in sdk['rustc_vv'] and '5f94df478' in sdk['cargo_vv']
        assert {k:v['sha256'] for k,v in sdk['components'].items()}=={
            'cargo-x86_64-unknown-linux-gnu':'d7674918d28093097614cd9728b6ca60db9ea3038f640f0bd1e9a4188c7568ce',
            'rustc-x86_64-unknown-linux-gnu':'77171ba2a0345fdf2abc4fedda55d6de078dae7a68527c28be8c77dcc9604bd5',
            'rust-std-x86_64-unknown-linux-gnu':'3e58dff2d0b72196b5ea4e90536e174d400de88564a52694686b81e091169933',
            'rust-std-aarch64-unknown-linux-gnu':'1cf7e2ef58ed1cfa6f1adea18e155cbf254c1951f39e5f5e3376879f55fd64a4'}
    else:
        assert n==119
        assert driver[0]==('45d8737f938d6ed97be5903342718f087d0af6ea710dd3c2416babc8c570d4b7' if role=='strict-C' else 'd38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084')
        assert cargo==('abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a' if role.startswith('signed') else '869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914')
        donor=read('donor-sdk.json')
        assert {f for f in sdk['files'] if sdk['files'][f]!=donor['files'][f]}=={'bin/cargo'}
    if tools is not None:
        assert tools['env']['CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER']=='/usr/bin/aarch64-linux-gnu-gcc'
        assert tools['env']['CARGO_NET_OFFLINE']=='true'
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
        cmd=['cargo','+ohm']+(['-Zohm-defaults=no'] if role=='signed-off' else [])+['build','-p','qa_app','--offline','--locked','--target',TARGET,'-j2','--message-format=json'];assert r['argv']==cmd
        selected=[av[1:] for values in events.values() for ep,av in values if Path(ep).name=='cargo' and ('/toolchains/ohm/bin/cargo' in ep or '/subject/bin/cargo' in ep)]
        assert selected==[cmd[2:]],(fn,selected,cmd)
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
        if path+'sources.json' in names:
            inputs=read(path+'sources.json');source=obj(inputs['plain/build.rs']).decode();leaf_source=obj(inputs['leaf/src/lib.rs']).decode()
            assert 'ldar {value}, [{ptr}]' in leaf_source and 'qa_leaf::atomic_value' in obj(inputs['plain/src/lib.rs']).decode()
            assert 'cargo:rustc-link-search=native=' in source and 'rerun-if-changed=build.rs' in source
            if kind=='bundled-unwatched':assert source.count('rerun-if-changed')==1
            elif kind=='bundled-both-directories':assert 'rerun-if-changed={}",dir.display()' in source and 'if name==' not in source
            elif kind in ('bundled-selected-file','bundled-all-files'):
                assert 'dir.join("libqa_owned_atomic.a")' in source and ('if name=="late"' in source)==(kind=='bundled-selected-file')
            else:raise AssertionError(kind)
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
    if terminal:assert len(cases)==sum(c['complete'] for c in cases)==ROLES[role] and len(infos)==9*ROLES[role]
    return {'role':role,'compiler':sdk['source'],'driver':driver,'cargo':sdk['files']['bin/cargo'],'file_objects':len(objs),'terminal':terminal,'visits':len(infos),'cases':cases,'divergences_from_empty':adverse,'full_roster_counts':dict(native_cmds)}
