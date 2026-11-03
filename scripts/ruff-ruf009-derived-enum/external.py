"""Independent proof that an empty Ruff history consumes the role's original registry outputs."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import prefix

PROBE = ''.join('#[derive(get_size_derive2::GetSize)]\nstruct '+name+' { #[get_size('+attrs+')] value:i32 }\n'
                for name,attrs in [('All','size=2,size_fn=demo,ignore'),('Ign','size=2,ignore'),
                    ('Fn','size=2,size_fn=demo'),('Bf','size_fn=demo,ignore'),('Ok','size=2')])

def digest(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(p.read_bytes())
def file_sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,why):
    if not ok:raise ValueError(why)

def actual_expansion(work,phase,macro,env,root):
    d=work/('expansion-'+phase);d.mkdir();probe=root/'registered-external-probe.rs'
    if not probe.exists():probe.write_text(PROBE)
    need(probe.read_text()==PROBE,'different direct proc macro fixture')
    argv=['rustc','+ohm','--edition=2024','--crate-type=lib','--crate-name','ordered_attributes',
          '--error-format=json','--extern','get_size_derive2='+str(macro),str(probe),'-Zunpretty=expanded']
    p=subprocess.run(argv,env=env,capture_output=True,timeout=45)
    (d/'stdout').write_bytes(p.stdout);(d/'stderr').write_bytes(p.stderr)
    prefix.record(d/'command.json',{'argv':argv,'exit':p.returncode,'source':digest(probe.read_bytes()),'macro':file_sha(macro)})
    return read_expansion(d)

def read_expansion(d):
    c=read(d/'command.json');need(c['exit']==1 and c['source']==digest(PROBE.encode()) and c['argv'][:2]==['rustc','+ohm'] and
        c['argv'][2:9]==['--edition=2024','--crate-type=lib','--crate-name','ordered_attributes','--error-format=json','--extern',c['argv'][-3]] and len(c['argv'])==11 and c['argv'][-3].startswith('get_size_derive2=/') and c['argv'][-1]=='-Zunpretty=expanded','unrecognized expansion contact')
    raw=(d/'stdout').read_bytes();stderr=(d/'stderr').read_bytes()
    need(b'get_heap_size_with_tracker' in raw and b'total += 2usize;' in raw,'compiler did not expand the valid registered derive')
    rows=[json.loads(l) for l in stderr.splitlines()]
    errors=[j for j in rows if j.get('level')=='error' and j.get('spans')]
    got=[(j['message'],next(s['line_start']for s in j['spans'] if s['is_primary']))for j in errors]
    choices=['`ignore` conflicts with mutually exclusive `size_fn`','`size` conflicts with mutually exclusive `size_fn`','`ignore` conflicts with mutually exclusive `size`']
    need(len(got)==4 and got[0][0] in choices and [x[1]for x in got]==[2,4,6,8] and
         [x[0]for x in got[1:]]==[choices[2],choices[1],choices[0]],'different ordered macro rule or syntax')
    return {'macro':c['macro'],'expanded':digest(raw),'errors':got,'stderr':digest(stderr)}


def local_owners(rows,workspace):
    return Counter((r['target']['name'].replace('-','_'),str(Path(r['target']['src_path']).relative_to(workspace)))for r in rows
                   if r.get('reason')=='compiler-artifact' and r['package_id'].startswith('path+file://'))

def physical_owners(trace,workspace,want,frontend,driver,macro):
    parents={};local=Counter();macro_read=[];probes=[];marker='"--crate-name", "';pids=[]
    for gz in trace.glob('trace.*.gz'):
        with gzip.open(gz,'rt') as f:
            real=[]
            for line in f:
                if line.startswith(('clone(','clone3(','<... clone resumed>','<... clone3 resumed>')):
                    child=re.search(r' = (\d+)$',line.rstrip())
                    if child:need(parents.setdefault(child[1],gz.name.split('.')[1])==gz.name.split('.')[1],'duplicated traced child')
                if line.startswith('execve(') and line.rstrip().endswith(' = 0') and marker in line and '"--crate-type"' in line:
                    exe=Path(re.match(r'execve\("([^"]+)"',line)[1])
                    if str(exe)!=str(frontend) and not str(exe).endswith('/toolchains/ohm/bin/rustc'):continue
                    if '"--out-dir"' not in line or '"--emit=' not in line:
                        need('"--print=' in line and '"-"' in line and '"--crate-name", "___"' in line,'unclassified rustc process')
                        probes.append([gz.name,digest(line.encode())]);continue
                    real.append(line)
                if 'PROT_EXEC' in line and '<'+str(macro)+'>' in line and re.search(r' = 0x[0-9a-f]+$',line.rstrip()):macro_read.append(gz.name)
            if not real:continue
        need(len(real)==1,'more than one frontend per compiler PID')
        ln=real[0];crate=ln.split(marker,1)[1].split('"',1)[0]
        args=re.findall(r'"([^"\\]*\.rs)"',ln)
        key=[(crate,str(Path(x).relative_to(workspace) if Path(x).is_absolute() and Path(x).is_relative_to(workspace) else Path(x))) for x in args]
        owner,=[x for x in key if x in want]
        with gzip.open(gz,'rt') as f:
            need(any('PROT_EXEC' in l and '<'+str(driver)+'>' in l and re.search(r' = 0x[0-9a-f]+$',l.rstrip()) for l in f),'missing role driver in cold compiler')
        pids.append([gz.name,crate,owner[1]]);local[owner]+=1
    need(local==want,('genuine independently empty local code',list((want-local).elements()),list((local-want).elements())))
    need(macro_read,'the compiled get-size-derive2 plugin was not opened by the cold rustcs')
    owners={p[0].split('.')[1]:p[1] for p in pids};relations={}
    for file in sorted(set(macro_read)):
        tid=file.split('.')[1];chain=[tid]
        while tid not in owners and tid in parents:
            tid=parents[tid];need(tid not in chain,'cycle in kernel ancestry');chain.append(tid)
        need(tid in owners,'macro mapping outside an actual registered local compiler')
        relations[file]=[owners[tid],chain]
    return dict(pids=sorted(pids),tool_queries=sorted(probes),macro_exec_mappings=relations)

def qualify_cold(instance,env,role,case):
    w=case.w
    case.source('buggy')
    d=w.OUT/'local-cold-physical';trace=w.OUT/'local-cold-trace';trace.mkdir()
    w.run(['/usr/bin/strace','-ff','-qq','-yy','-s','260000','-e','trace=execve,mmap,clone,clone3','-o',str(trace/'trace'),*case.CHECK],env,d,timeout=2400)
    instance.cold('check',d)
    for f in trace.glob('trace.*'):
        with f.open('rb')as src,gzip.open(str(f)+'.gz','wb',compresslevel=1)as dest:
            import shutil
            shutil.copyfileobj(src,dest,1<<20)
        f.unlink()
    kit=read(w.OUT/'kit.json');drivers=Path(kit['physical']['driver']['path'])
    report=physical_owners(trace,w.SRC,local_owners(prefix.events(d),w.SRC),kit['physical']['frontend']['path'],drivers,instance.macro)
    prefix.record(trace/'verified.json',report)
    return report


def originals(folder):
    # Reopen every hash row and the retained physical macro image, plus the exact measured source and kernel output.
    ext=folder/'registry-prefix';tab=gzip.decompress((ext/'external-members.json.gz').read_bytes())
    rows=json.loads(tab);seed=read(ext/'initialized.json');registry=read(ext/'registered-units.json')
    need(seed['sha256']==digest(tab) and seed['objects']==len(rows)>0 and seed['root_count']==len(read(ext/'owners.json')),'different prefix manifest')
    paths=read(ext/'owners.json');need(all(v.startswith('registry+')for v in paths.values()),'workspace data in retained prefix')
    kit=read(folder/'kit.json');root=Path(kit['physical']['frontend']['path']).parents[2]
    phases={k:folder/('dependency-seed-'+k) for k in ('check','build')}
    workspace=Path(next(r['manifest_path']for r in prefix.events(phases['check'])if r.get('reason')=='compiler-artifact' and r['target']['name']=='ruff_linter')).parents[2]
    reg=read(HERE/'registration.json');lock=ext/'Cargo.lock'
    need(file_sha(lock)==reg['lock']['sha256'],'different complete Cargo lock')
    known,states,expected_macro,locked_sources=prefix.parcel(root/'state',workspace,root/'cargo',tomllib.loads(lock.read_text()),phases,physical=False)
    need(known==paths and states==registry and str(expected_macro)==seed['macro_path'],'acquisition did not use authentic registered Cargo prefixes')
    need(len(registry['check']['local'])==37 and len(registry['check']['external'])==337,'different 374-unit focus')
    for name in rows:
        need(any(name.startswith(k+'/')for k in known),'manifest contains a foreign workspace product')
    input_archives=read(ext/'registry-archives.json')
    all_expected={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in tomllib.loads(lock.read_text())['package']if 'source' in p}
    need(input_archives==all_expected and len(all_expected)==reg['lock']['registry_archives'],'locked registry input mismatch')
    source_proof=read(ext/'source-packages.json');need(set(source_proof)==set(locked_sources),'wrong registry source roster')
    need(set(source_proof)=={r[0]for mask in registry.values()for r in mask['external']},'missing registry input source manifest')
    macro=Path(seed['macro_path']);names=[k for k in rows if str(macro).endswith('/'+k)];need(len(names)==1 and rows[names[0]][-1]==seed['macro_sha256'],'unbound macro body')
    restored=subprocess.check_output(['zstd','-dcq',ext/'compiled-macro.so.zst']);need(digest(restored)==seed['macro_sha256'] and restored[:4]==b'\x7fELF','unverified original proc macro')
    stages=read(ext/'stages.json')
    need(set(stages['cold'])=={'local-cold-physical','ordinary-buggy-cold','kernel-buggy-cold','empty-edit','native-buggy','native-empty-edit'},'missing independently empty frontend/bin histories')
    for label,kind in stages['cold'].items():
        obs=[]
        for r in prefix.events(folder/label):
            if r.get('reason')!='compiler-artifact':continue
            external=r['package_id'].startswith('registry+')
            need(r['fresh'] is external,'cold with pre-filled local Ruff/empty external')
            obs.append((external,[r['package_id'],r['target']['name'],r['target']['kind']]))
        need({k:sorted(v for e,v in obs if e==extflag) for k,extflag in [('external',True),('local',False)]}==registry[kind],'external graph changed on revisit')
    need(len(stages['observations'])>=10 and len(stages['observations'])==len(set(stages['observations'])),'incomplete source/compiled macro observations')
    signatures=[]
    for k in stages['observations']:
        physical=read(ext/(k+'-external-identity.json'));need(physical['files']==len(rows) and physical['sha256']==seed['sha256'] and physical['macro']==seed['macro_sha256'] and physical['source_census']==file_sha(ext/'source-packages.json') and physical['registry_archives']==file_sha(ext/'registry-archives.json'),'illegal external identity change')
        exp=ext/('expansion-'+k);need(read(exp/'command.json')['argv'][-3]=='get_size_derive2='+str(macro),'foreign proc macro expansion executable')
        sig=read_expansion(exp);need(sig['macro']==seed['macro_sha256'],'wrong physical dependency in expansion contact');signatures.append(sig)
    need(all(s==signatures[0]for s in signatures),'ordered macro expansion changed')
    cold=folder/'local-cold-physical';trace=folder/'local-cold-trace'
    actual=physical_owners(trace,workspace,local_owners(prefix.events(cold),workspace),kit['physical']['frontend']['path'],kit['physical']['driver']['path'],macro)
    need(actual==read(trace/'verified.json'),'different raw empty-owner witness')
    return dict(compiled_macro=seed['macro_sha256'],external_bytes=seed['bytes'],files=seed['objects'],units=seed['root_count'],source_census=digest((ext/'source-packages.json').read_bytes()),ordered=signatures[0],local_kernel=len(actual['pids']),cold=stages['cold'],boundaries=stages['observations'])
