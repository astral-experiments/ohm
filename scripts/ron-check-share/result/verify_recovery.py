#!/usr/bin/env python3
"""Reopen all signed recovery decisions, native execs, syscall reads and full Ron profiles."""
import ast
import collections
import gzip
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from profile_events import activities

HASH='ba90978f8720a4d8d8d54a12f5e970938d646dd85377e6a5be03bf3d28bd2d0c'
ROLES=('signed21','off21','signed20')
PHASES=('train-original','edit','repeat','invalid','repair-json','idle-human','idle-json','cache-reads',
        'bad-again','different-bad','unchanged-different-bad','different-repair','final-repair','empty-json','empty-human')
BAD={'invalid','bad-again','different-bad','unchanged-different-bad'}
STALE={'repair-json','idle-human','idle-json','cache-reads'}
WRONG='OHM_RON_CHECK_BAD_TYPE'
DIFFERENT='OHM_RON_SECOND_BAD_TYPE'
VALID='d560695aa852'
ORIGINAL = 'crates/ty_project/src/lib.rs'
def sha(b):return hashlib.sha256(b).hexdigest()
def load(path):
    if path.suffix=='.zip':
        assert path.stat().st_size==14345013 and sha(path.read_bytes())==HASH
        with zipfile.ZipFile(path) as z:
            assert len(z.namelist())==len(set(z.namelist()))==428 and z.testzip() is None
            raw={key:z.read(key) for key in z.namelist()}
            return {p:gzip.decompress(v) if p.endswith('.gz') else v for p,v in raw.items()}
    files={}
    with tarfile.open(path,'r|xz') as t:
        for entry in t:
            assert entry.isfile() and (entry.name=='INDEX.json' or entry.name.startswith('files/')) and '..' not in Path(entry.name).parts
            name=entry.name.removeprefix('files/')
            assert name not in files
            files[name]=t.extractfile(entry).read()
    index=json.loads(files.pop('INDEX.json'))
    assert index['zip_sha256']==HASH and len(files)==len(index['entries'])==428 and set(files)==set(index['entries'])
    for name,b in files.items():assert [len(b),sha(b)]==index['entries'][name][2:]
    return files

def parse_messages(stdout):
    return [json.loads(line) for line in stdout.splitlines()]

def decode_strace_read(raw,want_path,want):
    pre=raw.decode().splitlines()
    opens=[line for line in pre if 'openat(' in line and want_path in line]
    assert len(opens)==1 and '<cargo>' in opens[0] and '"'+want_path+'", O_RDONLY|O_CLOEXEC)' in opens[0]
    saved=[]
    for text in pre:
        match=re.search(r'^(\d+)<cargo> [0-9.]+ read\(\d+<'+re.escape(want_path)+r'>, (".*"), 8192\) = (\d+)$',text)
        if match:
            buf=ast.literal_eval('b'+match[2])
            assert len(buf)==int(match[3]) and opens[0].startswith(match[1]+'<cargo>')
            saved.append(buf)
    assert saved==[want,b'']
    return len(want)

def run(path):
    files=load(path)
    j=lambda name:json.loads(files[name])
    ci=j('cohort.json');su=j('subjects.json')
    assert ci['previous']['artifact']==13017707410 and not ci['normal_run'] and ci['preregistered_fraction']>.5
    assert j('followthrough-terminal.json')=={'failures':{},'preserve_original_red_gate':True}
    assert su['kit']['archive_sha256']=='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
    assert ci['kit20']['archive_sha256']=='edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15'
    assert su['kit']['provenance']['sources']['cargo']==ci['kit20']['provenance']['sources']['cargo'] and su['kit']['provenance']['sources']['rust']!=ci['kit20']['provenance']['sources']['rust']
    allroles={}
    for role in ROLES:
        default=role!='off21'
        physical=su['tools'] if role!='signed20' else ci['tools20']['tools']
        rolesummary={}
        cached=[]
        for phase in PHASES:
            p=role+'/'+phase+'/'
            rec=j(p+'receipt.json');src=rec['before']['source'];file=src[ORIGINAL]
            assert rec['before']['source']==rec['after']['source'] and rec['role']==role and rec['label']==phase
            assert rec['command'][:2]==['cargo','+ohm'] and ('-Zohm-defaults=no' in rec['command'])!=default
            assert (file['sha'].startswith(VALID),bool(file['bad']))==((phase not in BAD and phase!='different-repair'),phase in BAD)
            if phase=='different-repair':assert file['sha'].startswith('c4a6e67ee65a')
            if phase in ('invalid','bad-again'):assert file['sha'].startswith('0aa431793a70') and WRONG in file['bad'][0]
            if phase in ('different-bad','unchanged-different-bad'):assert file['sha'].startswith('a2b65c1d295e') and DIFFERENT in file['bad'][0]
            assert src[su['changed']]['sha']==su['original_blob' if phase=='train-original' else 'historical_parent_blob']
            stdout,stderr=files[p+'stdout.gz'],files[p+'stderr.gz']
            assert sha(stdout)==rec['stdout'] and sha(stderr)==rec['stderr']
            want_exit=101 if phase in BAD else 0
            assert rec['exit']==want_exit
            want_errors=phase in BAD or (default and phase in STALE)
            expected_workers=[]
            if rec['observer']=='physical':
                roots=[]
                for i,ln in enumerate(files[p+'trace/exec.tsv'].decode().splitlines(),1):
                    seq,pid,dev,ino,hit,exe=ln.split('\t');assert int(seq)==i
                    raw=files[p+f'trace/args-{i:04d}'];assert raw[-1:]==b'\0';args=[b.decode() for b in raw[:-1].split(b'\0')]
                    ident=[int(dev),int(ino)]
                    if ident==physical['cargo']['dev_ino']:
                        assert args[1:]==rec['command'][2:] and exe==physical['cargo']['physical'];roots.append(int(pid))
                    elif ident==physical['rustc']['dev_ino']:
                        assert exe==physical['rustc']['physical'] and '--out-dir' in args and '--emit=dep-info,metadata' in args
                        name=args[args.index('--crate-name')+1]
                        assert int(hit)==(name=='ron')
                        expected_workers.append(name)
                    else:assert Path(exe).name=='rustup'
                assert len(roots)==1 and roots==[v[0] for v in rec['physical_cargo']]
                assert expected_workers==[v[1] for v in rec['physical_rustcs']]
                expected=(['ron'] if default else [])+(['ty_project'] if phase in BAD|{'edit','different-repair','final-repair'} or phase=='repair-json' and not default else [])
                assert expected_workers==expected,(role,phase,expected_workers,expected)
            outputfiles={}
            for endpoint in ('before','after'):
                fingerprint=rec[endpoint]['cache']
                for key,val in fingerprint.items():
                    f=files['diag-content/'+val['sha']+'.gz']
                    assert (len(f),sha(f))==(val['size'],val['sha'])
                    if Path(key).name in ('output-test-lib-ty_project','test-lib-ty_project'):
                        outputfiles[(endpoint,Path(key).name)]=key,f
            cache=outputfiles.get(('after','output-test-lib-ty_project'))
            assert bool(cache)==want_errors
            if phase in BAD:assert outputfiles[('after','test-lib-ty_project')][1]==b''
            else:assert re.fullmatch(b'[0-9a-f]{16}',outputfiles[('after','test-lib-ty_project')][1])
            if phase=='repair-json':
                assert outputfiles[('before','test-lib-ty_project')][1]==b''
                assert file['mtime_ns']>cached[0] and file['ino']==cached[1]
                if default:
                    assert outputfiles['before','output-test-lib-ty_project']==cache
                    assert b'StaleDepFingerprint { unit: UnitIndex(91) }' in stderr and b"checking dep 'ron' build_state=BuiltUnchanged" in stderr
                    assert b"checking dep 'insta' build_state=SkippedEarlyCutoff" in stderr and b'early cutoff: skipping compilation of ty_project' in stderr
            if phase=='invalid':cached=[file['mtime_ns'],file['ino']]
            if rec['style']=='json':
                events=parse_messages(stdout);assert events[-1]=={'reason':'build-finished','success':not want_exit}
                art=[o for o in events if o['reason']=='compiler-artifact'];assert len(art)==(302 if want_exit else 303)
                m=[o for o in events if o['reason']=='compiler-message']
                assert len(m)==(2 if want_errors else 0)
                if m:
                    msg,note=[v['message'] for v in m]
                    assert all(o['target']['name']=='ty_project' and o['target']['src_path'].endswith(ORIGINAL) for o in m)
                    assert msg['level']=='error' and msg['code']['code']=='E0308' and note['level']=='failure-note'
                    loc,=[v for v in msg['spans'] if v['is_primary']]
                    assert loc['file_name']==ORIGINAL and loc['line_start']==1240 and (DIFFERENT if phase in ('different-bad','unchanged-different-bad') else WRONG) in loc['text'][0]['text']
                    cached_messages=parse_messages(cache[1])
                    for v in cached_messages:v['rendered']=re.sub(r'\x1b\[[\d;]*m','',v['rendered'])
                    first,aborting,last=cached_messages
                    assert aborting['level']=='error' and aborting['message']=='aborting due to 1 previous error' and not aborting['spans']
                    assert [first,last]==[msg,note]
                ta=[o for o in art if o['target']['name']=='ty_project']
                assert len(ta)==(0 if want_exit else 1)
                if ta:
                    assert rec['ty_artifacts'][0][1][0][1]['size']==0 and ta[0]['filenames']==[rec['ty_artifacts'][0][1][0][0]]
            else:
                assert stdout==b'' and ((b'error[E0308]' in stderr,b'OHM_RON_CHECK_BAD_TYPE' in stderr)==(want_errors,want_errors))
                assert b'Finished' in stderr and not want_exit
            if phase=='cache-reads' and default:
                assert decode_strace_read(files[p+'open-and-read.tsv.gz'],*cache)==2866
            rolesummary[phase]={'exit':want_exit,'error_diagnostic':want_errors,'rustcs':expected_workers if rec['observer']=='physical' else None,
                               'cache_bytes':len(cache[1]) if cache else 0,'source_sha256':file['sha']}
        allroles[role]=rolesummary
    profiles=[]
    for phase,pid,manifest in j('ron-profiles/visits.json'):
        base='ron-profiles/'+pid+'/'
        for name,(size,digest) in manifest.items():assert [len(files[base+name]),sha(files[base+name])]==[size,digest]
        argv=j(base+'invocation.json')['args']
        assert '--emit=dep-info,metadata' in argv and argv[argv.index('--crate-name')+1]=='ron' and not any('incremental=' in a for a in argv)
        flags=[a for a in argv if a.startswith('-Zself-profile')]
        assert len(flags)==1 and flags[0].startswith('-Zself-profile=') and flags[0].endswith('/'+pid)
        assert '-Ztime-passes-format=json' in argv and '-Ztime-passes' in argv
        data,=[f for f in manifest if f.endswith('.mm_profdata')]
        counts,all_intervals=activities(files[base+data])
        passes=[json.loads(l[6:]) for l in files[base+'timings.stderr'].splitlines() if l.startswith(b'time: ')]
        names=('macro_expand_crate','type_check_crate_interfaces','generate_crate_metadata','type_check_crate_bodies','MIR_borrow_checking','codegen_crate','link')
        measured={};intervals=[]
        for name in names:
            clock,=[r for r in passes if r['pass']==name]
            (_,tid,start,end),=[r for r in all_intervals if r[0]==name]
            assert .0<=end-start and abs(clock['time']-(end-start)/1e9)<.0003
            measured[name]=clock['time']*1000
            intervals.append([tid,start,end])
        assert len({i[0] for i in intervals})==1 and all(a[2]<=b[1] for a,b in zip(intervals,intervals[1:]))
        assert sum(r[0]=='codegen_module' for r in all_intervals)==0 and sum(r[0]=='expand_proc_macro' for r in all_intervals)==16
        total,=[r['time']*1000 for r in passes if r['pass']=='total'];measured['total']=total
        profiles.append({'visit':phase,'profile_sha256':sha(files[base+data]),'events':counts,'phase_ms':measured,
                         'macro_calls':16,'llvm_modules':0,'nonoverlap_sum_after_expansion_ms':sum(measured[name] for name in names[1:5])})
    return {'source_zip_sha256':HASH,'diagnostics':allroles,'phase_profiles':profiles}

if __name__=='__main__':
    path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('recovery-data.tar.xz')
    print(json.dumps(run(path),indent=2,sort_keys=True))
