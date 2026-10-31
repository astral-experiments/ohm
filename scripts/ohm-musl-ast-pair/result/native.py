"""Reopen the actual LNK1 body, ELF verdicts, independent pair and native selection."""
import argparse, gzip, hashlib, json, os, shutil, struct, subprocess, tarfile, tempfile, zipfile
from pathlib import Path

MARK='/dev/null/ohm-recheck-dependent-links-v2'
OLD='/dev/null/ohm-recheck-dependent-links'
HARD='/dev/null/ohm-untracked-relink-inputs'
MARKS={MARK,OLD,HARD}
def sha(b):return hashlib.sha256(b).hexdigest()
def run_image(b,want):
    assert b[:7]==b'\x7fELF\x02\x01\x01'
    assert len(b)<=5000000
    with tempfile.TemporaryDirectory() as folder:
        exe=Path(folder)/'guard-image';exe.write_bytes(b);exe.chmod(0o700)
        p=subprocess.run([exe],cwd=folder,env={},capture_output=True,timeout=7)
        assert (p.returncode,p.stdout,p.stderr)==(want,b'',b'')
def encoded(b,b3):
    i=0
    def get(n):
        nonlocal i;a=b[i:i+n];assert len(a)==n;i+=n;return a
    def u():return int.from_bytes(get(4),'little')
    def string():return os.fsdecode(get(u()))
    assert get(5)==b'\x01\0\0\0\xff';ver=get(1)[0];assert ver in (2,4);files=[]
    for _ in range(u()):
        kind=get(1)[0];name=string();cs=get(1)[0];assert kind in (0,1) and cs in (0,1)
        if cs:get(8);string()
        files.append([kind,name,cs])
    for _ in range(u()):
        string();has=get(1)[0];assert has in (0,1)
        if has:string()
    link=None
    if i<len(b):
        assert get(4)==b'LNK1';slot=u();assert 0<=slot<len(files)
        kind,link,cs=files[slot];assert kind==1 and cs==0 and link in (OLD,MARK)
        digest=bytes.fromhex(subprocess.check_output([b3],input=b[:i]).decode().split()[0]);assert digest==get(32)
    assert i==len(b)
    return {'version':ver,'LNK1':link,'markers':[name for _,name,_ in files if name in MARKS],'inputs':files}

def check(read,names,b3):
    programs={};dep_seen={};rows={};probed={};pairing={};rollbacks={};suites={};unknown=[]
    for n in sorted(names):
        if not n.endswith('/result.json'):continue
        prefix=n.rsplit('/',1)[0]+'/';case=prefix.rstrip('/').rsplit('/',1)[0]+'/';suite,flavor,label=prefix.strip('/').split('/')[-3:];j=json.loads(read(n));assert j['label']==label
        raw=read(prefix+'kernel.json');kernel=json.loads(raw);assert sha(raw)==j['kernel'] and sha(read(prefix+'syscalls.tgz'))==j['raw_trace']
        src=gzip.decompress(read(prefix+'build-script-stdout.gz')).decode().splitlines();assert len(src)==3 and src[0]=='cargo:rerun-if-changed=build.rs'
        typed=[json.loads(x) for x in gzip.decompress(read(prefix+'cargo.stdout.gz')).splitlines()];assert typed[-1]=={'reason':'build-finished','success':j['cargo']==0}
        paths,=[m['linked_paths'] for m in typed if m['reason']=='build-script-executed'];assert [s.removeprefix('cargo:rustc-link-search=') for s in src[1:]]==paths
        assert j['cargo']==kernel['status'];assert [r[0] for r in j['ld']]==[e['image'] for e in kernel['linkers']]
        for pid,stamp,parent,leader in kernel['opaque_rustc_thread_exits']:unknown.append([suite,flavor,label,pid,parent,leader])
        failed=kernel.get('failed_app_thread_exits',[])
        assert failed==j.get('failed_app_threads',[])
        if failed:
            peer=label.rsplit('-',1)[0]+('-empty' if label.endswith('-warm') else '-warm')
            other=json.loads(read(case+peer+'/result.json'))
            assert j['cargo']==other['cargo']==101 and not j['elf'] and not other['elf'] and j['verdict']==other['verdict']==None
            archive,=j['native'];ld,=kernel['linkers'];assert j['native']==other['native'] and j['native_files']==other['native_files'] and '/early/' in archive
            assert ld['exit']==1 and set(ld['selected'])=={archive} and any('linking with' in m['message']['rendered'] and archive+': file format not recognized' in m['message']['rendered'] for m in typed if m['reason']=='compiler-message' and m['message']['level']=='error')
            app,=[r for r in kernel['compilers'] if r['crate']=='ohm_v2_app'];obs={row[0]:row[3] for row in kernel['opaque_rustc_thread_exits']};assert all(obs[tid]==leader==app['pid'] for tid,leader in failed)
        dep=json.loads(read(prefix+'dep-files.json'))
        for k in ('before','after'):
            for r in dep[k]:
                tag=r['raw_sha256']
                if tag in dep_seen:
                    assert dep_seen[tag]==r['parsed'];continue
                b=read(case+'cas/'+tag);assert sha(b)==tag and len(b)==r['identity'][2]
                if r['kind']=='encoded':c=encoded(b,b3)
                else:
                    lines=b.decode().splitlines();c=[l[:-1] for l in lines if l.endswith(':') and l[:-1] in MARKS]
                    rules=[line.split(': ',1) for line in lines if ': ' in line];own=[rhs for lhs,rhs in rules if Path(lhs).name==Path(r['path']).name]
                    assert len(own)==1 and not set(own[0].split())&MARKS and [k for k in rules[0][1].split() if k in MARKS]==c and len(c)<=1
                assert c==r['parsed'];dep_seen[tag]=c
        if j['elf']:
            key=j['elf'];e=gzip.decompress(read(case+'cas/'+key+'.elf.gz'));assert sha(e)==key
            if key not in programs:run_image(e,j['verdict']);programs[key]=j['verdict']
            assert programs[key]==j['verdict']
        else:assert j['verdict'] is None and j['cargo']==101
        if label.endswith('-warm'):
            pre=label.removesuffix('-warm');ref=json.loads(read(case+pre+'-empty/result.json'));assert [j[k] for k in ('cargo','verdict','elf')]==[ref[k] for k in ('cargo','verdict','elf')]
            pairing.setdefault(suite,[]).append([flavor,pre,j['verdict'],j['elf']])
        if label=='old-reader-of-LNK1-warm':
            prior=[x for x in dep['before'] if x['path']==j['producer_dep_record'] and x['kind']=='encoded'];assert len(prior)==1 and prior[0]['parsed']['LNK1']==MARK
            calls=[(stamp,pid) for stamp,pid,path in kernel['dep_read'] if path==j['producer_dep_record']]
            assert calls and not any(t<=min(calls)[0] and (w==j['producer_dep_record'] or (w is None and j['producer_dep_record'] in line)) for t,_,w,line in kernel['dep_writes'])
            assert j['cargo']==101 and j['producer']==['full'] and len(j['ld'])==1 and j['ld'][0][2]!=0
            rollbacks[suite]={'previous_bytes':prior[0]['raw_sha256'],'prior_inode':prior[0]['identity'],'cargo_reader_pid':min(calls)[1],'true_linker':j['ld'][0],'active':j['producer_dep_record']}
        if flavor=='candidate-v2' and label.endswith('-warm') and not label.startswith('cold-'):
            assert not j['producer'] and not j['build_scripts'] and len(j['ld'])==1 and len(j['native'])==1
            pro=[x for x in dep['after'] if x['path']==j['producer_dep_record']];assert len(pro)==1 and pro[0]['parsed']['LNK1']==MARK
        suites[suite]=suites.get(suite,0)+1
        rows.setdefault(suite,{}).setdefault(flavor,[]).append([label,j['cargo'],j['verdict'],j['producer'],j['consumer'],[Path(x).name for x in j['native']]])
    return {'visits':suites,'paired_cases':{k:len(v) for k,v in pairing.items()},'reexecuted_musl_images':programs,'redecoded_unique_depfiles':len(dep_seen),'prior_v2_before_write':rollbacks,'opaque_rustc_exit_records':unknown,'actual':rows}
