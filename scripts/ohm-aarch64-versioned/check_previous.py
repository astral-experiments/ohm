"""Replay the real compiler/Cargo depfiles that stopped the first ordinary cold run."""
from pathlib import Path
import hashlib,io,json,os,sys,tempfile,zipfile,subprocess
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from outputs import read_files
from version_kit import sha,save
R=41083038179;Q='743fcbf759fef2c367210f7078742af76964e564';O='astral-experiments/ohm'
def main(gh,output):
    get=lambda route:subprocess.check_output([gh,'api',f'repos/{O}/'+route])
    state=json.loads(get(f'actions/runs/{R}'));assert state['head_sha']==Q and state['status']=='completed' and state['conclusion']=='failure'
    jobs=json.loads(get(f'actions/runs/{R}/jobs'))['jobs'];arts={x['name']:x for x in json.loads(get(f'actions/runs/{R}/artifacts'))['artifacts']}
    rows={};good={}
    for j in jobs:
        mode=j['name'].split()[-1];a=arts['gnu-versioned-native-'+mode]
        assert a['workflow_run']['head_sha']==Q and not a['expired'] and 0<a['size_in_bytes']<2**20
        orig=get(f"actions/artifacts/{a['id']}/zip");assert len(orig)==a['size_in_bytes'] and 'sha256:'+hashlib.sha256(orig).hexdigest()==a['digest']
        z=zipfile.ZipFile(io.BytesIO(orig));assert z.testzip() is None and len(set(z.namelist()))==len(z.namelist())
        if mode in ('named','direct'):
            assert j['conclusion']=='success';term=mode+'-terminal.json';good[mode]={'artifact':a['digest'],'terminal':hashlib.sha256(z.read(term)).hexdigest()}
            if mode=='named':
                for kind in ('none','v1','v2','both'):
                    c=json.loads(z.read('named-'+kind+'/complete.json'));assert c['mode']==kind and len({v['body'] for v in c['cases'].values()})==1
                    repeat=c['cases']['repeat'];assert bool(repeat['physical_root_rustcs'])==(kind!='none')
                    for f in repeat['files'].values():
                        if f['kind']=='encoded':assert f['has_LNK1']==(kind=='none') and f['marker_v2']
            else:
                for role in 'PC':
                    c=json.loads(z.read('direct-version-'+role+'/complete.json'));assert len(c['cases'])==29
            continue
        assert j['conclusion']=='failure'
        folder=mode+'-undeclared-direct/'
        cmd=json.loads(z.read(folder+'cold-lower/result.json'))
        assert cmd['exit']==0 and cmd['answer']=='17 7' and cmd['actual_GNU_linkers']
        bodies={str(n).rsplit('/',1)[1]:z.read(n) for n in z.namelist() if n.startswith(folder+'raw-depfiles/')}
        translated=[z.read(n) for n in z.namelist() if n.startswith(folder+'cold-lower/actual-files/') and z.read(n)[4:5]==b'\xff']
        assert len(bodies)==2 and len(translated)==1,(mode,bodies.keys())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'src';src.mkdir()
            for key,body in bodies.items():
                assert hashlib.sha256(body).hexdigest()==key
                target=src/('export' if len(body.splitlines())==1 else 'compiler');target.mkdir();(target/'qa_owned_test.d').write_bytes(body)
            fp=src/'fingerprint';fp.mkdir();(fp/'dep-bin-qa_owned_test').write_bytes(translated[0])
            got=read_files(root,[src],'qa_owned_test')
            assert {x['kind'] for x in got.values()}=={'depfile','encoded','cargo-exported-depfile'}
            encoded,=[x for x in got.values() if x['kind']=='encoded']
            legacy=mode=='legacy-writer';aware=mode in ('aware','legacy-writer')
            assert encoded['has_LNK1']==aware and encoded['marker_v2']==(not legacy)
            rust,=[x for x in got.values() if x['kind']=='depfile'];mark='/dev/null/ohm-recheck-dependent-links'+('' if legacy else '-v2')
            assert rust['first']==[mark] and rust['fake']==[mark] and not rust['ordinary']
            rows[mode]={'artifact':a['digest'],'typed_binary':cmd['elf'],'raw_depfiles':sorted(bodies),'encoded':encoded['sha256'],'LNK1':encoded['has_LNK1'],'actual_GNU_linkers':len(cmd['actual_GNU_linkers'])}
    assert set(good)=={'named','direct'} and len(rows)==6
    save(output,{'original_run':R,'QA':Q,'two_native_terminals':good,'six_authentic_reader_replays':rows})
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
