"""Bind the two original Ruff arms and exact source kit to a positive native provider replay."""
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
PIN=json.loads((HERE/'original-source-and-ordinary.json').read_text())
BASE=json.loads((HERE/'parent.json').read_text())['files']
SOURCE=json.loads((HERE/'source.json').read_text())
JOBS={layout:f'Unbundled native provider ({layout})' for layout in ('private','shared')}
SUITES={'mechanism':42,'signed':26,'strict':26}
SHA=lambda data:hashlib.sha256(data).hexdigest()
API='repos/astral-experiments/ohm/actions/'

def raw(p):return subprocess.check_output([os.environ.get('MUSL_EVIDENCE_GH','gh'),'api',API+p])
def get(p):return json.loads(raw(p))
def jobset(run):return get(f'runs/{run}/jobs?per_page=100')['jobs']
def file_json(z,name):return json.loads(z.read(name))

def enrolled(run,head,status):
    r=get(f'runs/{run}')
    assert (r['id'],r['event'],r['head_sha'],r['head_branch'],r['run_attempt'],r['status'],r['conclusion'])==(run,'workflow_dispatch',head,PIN['branch'],1,'completed',status),r
    jobs=jobset(run);assert all(x['head_sha']==head and x['run_id']==run and x['run_attempt']==1 for x in jobs)
    assert len({x['name'] for x in jobs})==len(jobs)
    return {x['name']:x for x in jobs}

def arc(run,head,name,id_,digest,size):
    a=get(f'artifacts/{id_}')
    assert (a['name'],a['workflow_run']['id'],a['workflow_run']['head_sha'],a['digest'],a['size_in_bytes'],a['expired'])==('musl-285-'+name,run,head,'sha256:'+digest,size,False),a
    b=raw(f'artifacts/{id_}/zip');assert len(b)==size and SHA(b)==digest
    z=zipfile.ZipFile(io.BytesIO(b));names=z.namelist();assert len(names)==len(set(names))
    return z

def original():
    run,head=PIN['run'],PIN['head'];jobs=enrolled(run,head,'failure')
    assert set(jobs)=={r['name'] for r in PIN['records'].values()}
    roles={r:BASE|{next(n for n in BASE if n.startswith('lib/librustc_driver-')):PIN['driver'][r]} for r in 'PC'}
    t=PIN['records']['source-transfer'];seal=PIN['identity']
    expected={'run':run,'head':head,'transfer_id':t['artifact'],'transfer_digest':t['sha256'],'identity_sha256':seal}
    for name,r in PIN['records'].items():
        j=jobs[r['name']];assert (j['id'],j['status'],j['conclusion'])==(r['job'],'completed',r['conclusion'])
        if name=='source-transfer':
            # restore.py reads the entire original transfer and authenticates all 183 files and each loose ELF.
            continue
        with arc(run,head,name,r['artifact'],r['sha256'],r['bytes']) as z:
            if name=='source-records':
                q='musl-ast/pair-receipts/';assert file_json(z,q+'transfer.json')==expected
                parts=file_json(z,q+'qualified.json');assert parts['roles']==roles and parts['source']==SOURCE
                for role,status in [('P',1),('C',0)]:
                    v=file_json(z,q+role+'-run-make.json');assert v['status']==status and v['command'][0:2]==['--set','rust.verbose-tests=true']
                    log,=[s for s in z.namelist() if s.endswith('/cmp-'+role+'-run-make.log')]
                    assert SHA(z.read(log))==v['log']
            elif name.startswith('ordinary'):
                role=name[-1];sdk=file_json(z,'sdk.json');assert sdk['installed']==roles[role] and sdk['source']==SOURCE
                q=file_json(z,'qualified-ordinary.json');assert q['role']==role and q['source']==SOURCE and all(q['structural'].values()) and set(q['structural'])=={'build','test','hard-native'}
                for mode in ('build','test'):
                    a=file_json(z,mode+'/terminal.json');assert a['full_byte_gate_passed'] and all(a['same_entire_elf'].values())
                    for phase in ('unchanged','second-unchanged'):
                        t0=a['visits'][phase];full=[c for c,_,_,only in t0['emitted'] if not only]
                        assert len(full)==(3 if role=='P' else 0)
                assert (sdk['source_transfer']['run'],sdk['source_transfer']['id'],sdk['source_transfer']['identity'],sdk['source_transfer']['archive'])==(run,t['artifact'],seal,t['sha256'])
                a=file_json(z,'ordinary/terminal.json');assert a['role']==role and a['all']['invalid']['exit']==101 and all(a['all'][k]['observed']['client']==a['clean'] for k in ('edit','repeat','repair','empty'))
            else:
                assert not any(p.endswith(('/result.json','/terminal.json','/complete.json')) for p in z.namelist())
                for k in SUITES:
                    u=file_json(z,'musl-guard-raw/'+k+'/refused.json')
                    assert u['last_closed']==[] and 'use same-filesystem private scratch' in u['traceback'] and 'driver-P' in u['traceback']
    return {'SOURCE_RUN':str(run),'SOURCE_HEAD':head,'TRANSFER_ID':str(t['artifact']),'TRANSFER_DIGEST':t['sha256'],'TRANSFER_SEAL':seal}

def prior_native():
    p=json.loads((HERE/'prior-native-replay.json').read_text());run,head=p['run'],p['head']
    jobs=enrolled(run,head,'failure');assert set(jobs)==set(JOBS.values())
    for layout,row in p['records'].items():
        job=jobs[JOBS[layout]];assert (job['id'],job['conclusion'])==(row['job'],row['conclusion'])
        with arc(run,head,'native-'+layout,row['artifact'],row['sha256'],row['bytes']) as z:
            names=z.namelist()
            for suite,num in row['closed'].items():
                assert len([n for n in names if n.startswith(suite+'/') and n.endswith('/result.json')])==num
            refused=[n for n in names if n.endswith('/refused.json')]
            if layout=='shared':assert not refused;continue
            assert refused==['signed/refused.json'] and 'exited with 0' in file_json(z,refused[0])['traceback']
            d=p['partial'];body=z.read(d+'syscalls.tgz');assert SHA(body)==p['unclosed_syscalls_sha256']
            typed=[json.loads(l) for l in gzip.decompress(z.read(d+'cargo.stdout.gz')).splitlines()]
            assert typed[-1]=={'reason':'build-finished','success':False}
            assert any('libohm_musl_v2_choice.a: file format not recognized' in m['message']['rendered'] for m in typed if m['reason']=='compiler-message')
            with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as tar:
                assert len(tar.getnames())==p['tracees']
                text=lambda pid:tar.extractfile('pid.'+str(pid)).read().decode().splitlines()
                worker,rustc,ld,cargo=[text(p[k]) for k in ('thread','rustc','linker','cargo')]
                assert len(worker)==2 and worker[0].endswith(' ???( <unfinished ...>') and worker[1].endswith(' +++ exited with 1 +++')
                assert rustc[-1].endswith(' +++ exited with 1 +++') and any('execve(' in l and '"--crate-name", "ohm_v2_app"' in l for l in rustc)
                assert any('CLONE_THREAD' in l and l.endswith('= '+str(p['thread'])) for l in rustc)
                assert ld[-1].endswith(' +++ exited with 1 +++') and any('execve("/usr/bin/ld"' in l for l in ld) and cargo[-1].endswith(' +++ exited with 101 +++')
                fd=[int(m[1]) for l in ld if '/native/early/libohm_musl_v2_choice.a"' in l and (m:=re.search(r'= ([0-9]+)<[^>]+/native/early/libohm_musl_v2_choice.a>$',l))]
                assert fd==p['opened_bad_provider_fds']

def provider(run,head,source):
    prior_native()
    assert run!=PIN['run'] and head!=PIN['head']
    jobs=enrolled(run,head,'success');assert set(jobs)==set(JOBS.values()) and all(x['conclusion']=='success' for x in jobs.values())
    arts=get(f'runs/{run}/artifacts?per_page=100')['artifacts'];assert {x['name'] for x in arts}=={'musl-285-native-'+layout for layout in JOBS} and len(arts)==2
    receipts={}
    for layout,jname in JOBS.items():
        art,=[x for x in arts if x['name']=='musl-285-native-'+layout];digest=art['digest'].removeprefix('sha256:')
        with arc(run,head,'native-'+layout,art['id'],digest,art['size_in_bytes']) as z:
            assert not any(n.endswith('/refused.json') for n in z.namelist())
            kit=file_json(z,'source-proof.json');assert kit==source
            mount=file_json(z,'storage.json');assert mount['filesystem'] in ('ext4','tmpfs') and mount['same_regular_hardlink'] is True and mount['exec'] is True
            flat=file_json(z,'source-sdk.json');assert flat['installed']==BASE and flat['source_transfer']['archive']==source['TRANSFER_DIGEST'] and flat['source_transfer']['identity']==source['TRANSFER_SEAL']
            donor=file_json(z,'regular-aliases.json');assert set(donor)=={'P','C','aware','strict','signed','rustc','rustdoc'}
            hashes={role:PIN['driver'][role][0] for role in 'PC'}
            hashes.update(rustc=BASE['bin/rustc'][0],rustdoc=BASE['bin/rustdoc'][0],aware=BASE['bin/cargo'][0],
                          signed='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e',strict='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4')
            assert {name:info['sha256'] for name,info in donor.items()}==hashes and all(i['donor']==i['alias'] for i in donor.values())
            assert mount['tools']['strace'][1]=='28f957c227012de0b18d1bd7fff2d396cb693ea60ed8013be68de071e84b5001'
            for suite,n in SUITES.items():
                prefix=suite+'/';registration=file_json(z,prefix+'enrolled.json')
                assert registration['originals']=={k:SHA((HERE/'v2'/k).read_bytes()) for k in ('guard.py','evidence.py','fixture.py','subjects.py')}
                finish=file_json(z,prefix+'complete.json');assert finish['layout']==layout and finish['legacy']==(None if suite=='mechanism' else suite)
                names={'candidate-v2','parent-hard','marker-free-sham','veto-bundled','veto-unknown'} if suite=='mechanism' else {'transition'}
                assert set(finish['histories'])=={name+'/terminal.json' for name in names}
                visits=0
                for path,sha in finish['histories'].items():
                    history=z.read(prefix+path);assert SHA(history)==sha;h=json.loads(history)
                    if suite!='mechanism':assert len(h['pretranslated'])==1 and h['pretranslated'][0]['observed_prior_v2']
                    case=prefix+str(Path(path).parent)+'/'
                    seen=set();rows={r['label']:r for r in h['phases']};assert len(rows)==len(h['phases'])
                    for row in h['phases']:
                        label=row['label'];root=case+label+'/'
                        if label.endswith('-warm'):
                            ref=rows[label.removesuffix('-warm')+'-empty'];assert [row[k] for k in ('cargo','verdict','elf')]==[ref[k] for k in ('cargo','verdict','elf')]
                        else:assert label.endswith('-empty') and label.removesuffix('-empty')+'-warm' in rows
                        if row['elf'] is not None and row['elf'] not in seen:
                            e=gzip.decompress(z.read(case+'cas/'+row['elf']+'.elf.gz'));assert e[:6]==b'\x7fELF\x02\x01' and SHA(e)==row['elf'];seen.add(row['elf'])
                        assert file_json(z,root+'result.json')==row and SHA(z.read(root+'syscalls.tgz'))==row['raw_trace'] and SHA(z.read(root+'kernel.json'))==row['kernel']
                        raw_msgs=gzip.decompress(z.read(root+'cargo.stdout.gz')).splitlines();assert json.loads(raw_msgs[-1])=={'reason':'build-finished','success':row['cargo']==0}
                        if row['failed_app_threads']:
                            mate=rows[label.rsplit('-',1)[0]+('-empty' if label.endswith('-warm') else '-warm')]
                            assert label.rsplit('-',1)[0] in {'bad','bad-repeat','malformed','old-reader-of-LNK1','child-driver-malformed'}
                            assert row['cargo']==mate['cargo']==101 and row['elf']==mate['elf']==row['verdict']==mate['verdict']==None
                            native,=row['native'];assert '/early/' in native and row['native']==mate['native'] and row['native_files']==mate['native_files']
                            assert len(row['ld'])==1 and row['ld'][0][2]==1
                            errors=[m['message']['rendered'] or m['message']['message'] for b in raw_msgs if (m:=json.loads(b))['reason']=='compiler-message' and m['message']['level']=='error']
                            assert any('linking with' in e and native+': file format not recognized' in e for e in errors)
                    visits+=len(h['phases'])
                assert visits==n,(suite,visits)
            receipts[layout]=[jobs[jname]['id'],art['id'],digest]
    return receipts

def locate(run,head):
    source=original();provider(run,head,source)
    return source|{'PROVIDER_RUN':str(run),'PROVIDER_HEAD':head}

if __name__=='__main__':
    assert sys.argv[1:]==['original']
    print(json.dumps(original(),sort_keys=True))
