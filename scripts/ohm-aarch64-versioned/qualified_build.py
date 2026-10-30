"""Read the original native construction and its failed pre-compiler qualification, independently."""
from pathlib import Path
from hashlib import sha256
import gzip
import io
import json
import subprocess
import sys
import zipfile
O='astral-experiments/ohm';R=41081958994;Q='78801e0c551576349aa36eaf39a4f8afbd291b7f'
HERE=Path(__file__).resolve().parent
PLAN=json.loads((HERE/'sources.json').read_bytes())
ART={'gnu-versioned-marker-compiler-receipts':[12990820176,36345,'eb1a3f19bf6f88ba92cda9a56b965c5a502b6828925b650a6839a8d933287390'],
     'gnu-versioned-marker-compiler-pair':[12989079541,230773437,'d376d08d72d6a4974aba77cf185acb6f4622f2f4646a2fe83b472e0438af4090'],
     'gnu-versioned-cargo-build-receipts':[12989647504,2817961,'8b52635ef598c77f10de34d09f4ce57a983f3d75e4766eb60b8038c2cac1d7ad'],
     'gnu-versioned-cargo-product':[12989289345,17646761,'04fb512671e1d346e18fed8aed59ab69a6e6a939ce3d8a155a1823e8e42f1518']}
def H(b):return sha256(b).hexdigest()
def get(gh,endpoint):return subprocess.check_output([gh,'api',f'repos/{O}/'+endpoint])
def jar(gh,k):
    i,n,h=ART[k];wire=get(gh,f'actions/artifacts/{i}/zip');assert len(wire)==n and H(wire)==h
    z=zipfile.ZipFile(io.BytesIO(wire));assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None
    assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in z.namelist())
    return z
def review(gh):
    wf=json.loads(get(gh,f'actions/runs/{R}'))
    assert (wf['head_sha'],wf['status'],wf['conclusion'],wf['run_attempt'])==(Q,'completed','failure',1)
    arts={j['name']:j for j in json.loads(get(gh,f'actions/runs/{R}/artifacts'))['artifacts']}
    assert set(arts)==set(ART)
    for n,(i,sz,h) in ART.items():
        a=arts[n];assert not a['expired'] and a['workflow_run']['head_sha']==Q and (a['id'],a['size_in_bytes'],a['digest'])==(i,sz,'sha256:'+h)
    jobs={j['id']:j for j in json.loads(get(gh,f'actions/runs/{R}/jobs'))['jobs']}
    rust,cargo=jobs[124153122699],jobs[124153123487]
    assert rust['conclusion']=='failure' and cargo['conclusion']=='success'
    failures=[s['name'] for s in rust['steps'] if s['conclusion']=='failure']
    assert failures==['Exercise both live compilers on each true and conservative assembler and provider case'],failures
    assert any(s['conclusion']=='success' and s['name']=='Run both checked-in Linux host assembler controls on the real child' for s in rust['steps'])
    log=subprocess.check_output([gh,'api','--allow-escape-sequences',f"repos/{O}/actions/jobs/{rust['id']}/logs"]);error=b"cannot import name 'PRIOR' from 'classifier'"
    assert error in log and b'ohm-aarch64-registers/classifier.py' in log
    re=jar(gh,'gnu-versioned-marker-compiler-receipts');cb=jar(gh,'gnu-versioned-cargo-build-receipts');cp=jar(gh,'gnu-versioned-cargo-product')
    assert set(cp.namelist())=={'cargo','product.json'}
    product=cp.read('product.json');assert cb.read('cargo-293-source/verified.json')==product
    pub=json.loads(product);elf=cp.read('cargo')
    assert pub['git']==PLAN['cargo']['source'] and pub['source']['parent']==PLAN['cargo']['parent'] and pub['tree']==PLAN['cargo']['tree']
    assert PLAN['cargo']==pub['source']['source_changes'] and pub['source']['entries']==3114 and pub['source_workflow']==Q
    assert pub['cargo_sha256']==H(elf) and pub['raw_bytes']==len(elf) and elf[:6]==b'\x7fELF\x02\x01' and int.from_bytes(elf[18:20],'little')==62
    assert pub['mode']==0o755 and pub['features']=='ohm-defaults,all-static' and pub['builder']=='abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a'
    assert pub['git'] in pub['version'] and '1 passed; 0 failed;' in gzip.decompress(cb.read('cargo-293-source/marker-unit/stdout.gz')).decode()
    native=cb.read('cargo-293-source/native-exec.tar.gz');assert H(native)==pub['native_trace']
    rows=list(map(json.loads,gzip.decompress(cb.read('cargo-293-source/construction/stdout.gz')).splitlines()))
    assert rows[-1]=={'reason':'build-finished','success':True} and sum(r.get('reason')=='compiler-artifact' for r in rows)==pub['typed_units']==389
    assert pub['source']==json.loads(cb.read('cargo-293-source/source.json')) and pub['native_physical_cargo_rustc_events']>=390
    cap=json.loads(re.read('sdk-custody.json'))
    assert re.read('qa-head').decode().strip()==Q and json.loads(re.read('versioned-source.json'))==PLAN['rust'] and re.read('x86-host-run-make-pass').decode().strip()==PLAN['rust']['source']
    assert not any('direct-version-' in n for n in re.namelist())
    file_tables={r:json.loads(re.read(r+'-sdk.json')) for r in 'PC'}
    assert (file_tables['P']['source'],file_tables['C']['source'],file_tables['C']['tree'])==(PLAN['rust']['parent'],PLAN['rust']['source'],PLAN['rust']['tree'])
    assert file_tables['P']['bootstrap']==file_tables['C']['bootstrap']
    members={r:j['files'] for r,j in file_tables.items()};assert members['P'].keys()==members['C'].keys() and len(members['P'])==117
    changes=[p for p in members['P'] if members['P'][p]!=members['C'][p]]
    one,=changes;assert one.startswith('lib/librustc_driver')
    drivers={r:members[r][one][0] for r in 'PC'};assert drivers['P']=='2a232a6c250f30b7c8214be0bbba21ef125f514da3dfd720291c377909d14545'
    return {'run':R,'QA':Q,'artifacts':ART,'capsule':cap['sha256'],'drivers':drivers,'changed_SDK_member':one,
            'source':PLAN,'members_per_role':119,'cargo_elf':pub['cargo_sha256'],'cargo_manifest':H(product),'cargo_kernel_receipt':H(native),
            'root_compilers':pub['compiler_root_argv'],'typed':pub['typed_units'],'cargo_unit':H(cb.read('cargo-293-source/marker-unit/stdout.gz')),
            'x86_host_tests':H(re.read('x86-host-run-make.log')),'native_original_exception':error.decode(),'original_job_log':H(log),
            'subjects':{r:H(re.read(r+'-sdk.json')) for r in 'PC'},'complete_archive_verification':'per-member in every qualification runner'}
if __name__=='__main__':
    data=review(sys.argv[1]);wire=(json.dumps(data,sort_keys=True,indent=2)+'\n').encode();Path(sys.argv[2]).open('xb').write(wire);print(data['drivers'],data['cargo_elf'],H(wire))
