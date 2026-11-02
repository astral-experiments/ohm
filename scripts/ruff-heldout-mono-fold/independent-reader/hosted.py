"""Verify only the original frozen six workers. The reader owns no performance samples."""
import gzip,hashlib,json,os,re,shutil,subprocess,sys,tarfile,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;OUT=Path(os.environ['RUNNER_TEMP'])/'heldout-independent-reader';RUN=41442143564;HEAD='34a6dc52b4543454e7512018ce0586a562d8a03c';REPO='astral-experiments/ohm';JOBS=[125266369213,125266369680,125266369669,125266369622,125266369767,125266369730]

def need(x,msg):
    if not x:raise ValueError(msg)

def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()

def api(p):return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+'/actions/'+p]))
def save(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')

def acquire():
    need(os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1' and shutil.disk_usage(OUT.parent).free>(19<<30),'wrong reader or inadequate initial disk reserve');shutil.copytree(HERE,OUT);run=api(f'runs/{RUN}');jobs=api(f'runs/{RUN}/attempts/1/jobs?per_page=30');arts=api(f'runs/{RUN}/artifacts?per_page=30');need(run['conclusion']=='success'and run['head_sha']==HEAD and run['run_attempt']==1 and run['event']=='workflow_dispatch'and jobs['total_count']==arts['total_count']==6,'incomplete or different independent cohort');jlist={z['id']:z for z in jobs['jobs']};need(set(jlist)==set(JOBS)and len({z['runner_id']for z in jlist.values()})==6 and len({z['runner_name']for z in jlist.values()})==6,'not six independent source workers');provenance={}
    for a in arts['artifacts']:
        m=re.fullmatch(r'ruff-27470-matched-confirmation-([1-6])',a['name']);need(m is not None,'unregistered artifact');slot=int(m[1]);j=jlist[JOBS[slot-1]];need(slot not in provenance and j['name']==f'Ruff library-test confirmation boot {slot}' and j['conclusion']=='success'and j['runner_id']>0 and a['workflow_run']['id']==RUN and a['workflow_run']['head_sha']==HEAD and not a['expired']and 0<a['size_in_bytes']<330<<20,'foreign or partial raw evidence');f=OUT/f'slot-{slot}-{a["id"]}.zip';
        with f.open('xb')as out:subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{a["id"]}/zip'],stdout=out,check=True,timeout=350)
        need(f.stat().st_size==a['size_in_bytes']and 'sha256:'+sha(f)==a['digest']and shutil.disk_usage(OUT).free>15<<30,'wrong raw ZIP SHA, size or disk guard');provenance[slot]=dict(slot=slot,job=j,artifact=a,file=f.name)
    need(set(provenance)==set(range(1,7)),'unknown source set');save(OUT/'github-provenance.json',dict(run=run,slots=provenance));own=api(f'runs/{os.environ["GITHUB_RUN_ID"]}/attempts/1/jobs?per_page=5');reader,=own['jobs'];need(reader['runner_name']==os.environ['RUNNER_NAME'] and reader['name']=='Independently reopen six immutable Ruff builds'and reader['runner_id']not in {j['runner_id']for j in jlist.values()},'source and reader workers are not disjoint');save(OUT/'reader-identity.json',dict(run=int(os.environ['GITHUB_RUN_ID']),job=reader['id'],head=os.environ['GITHUB_SHA'],runner=reader['runner_name'],runner_id=reader['runner_id'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()))

def package():
    summary=json.loads((OUT/'reopened-with-execution.json').read_bytes());own=json.loads((OUT/'reader-identity.json').read_bytes());need(summary['workers']==6 and summary['extra_local_execution']and own['boot']not in {s['boot']for s in summary['all_native']},'not an independent physical replay');shutil.copyfile(OUT/'reopened-with-execution.json',OUT/'reopened.json');subprocess.run([sys.executable,'-I','-B',OUT/'compact.py'],check=True);meta=json.loads((OUT/'github-provenance.json').read_bytes());archive=OUT/'compact-evidence';archive.mkdir();small=OUT/'verification-evidence';small.mkdir();pool=OUT/'native-evidence';pool.mkdir();native={};raw={}
    for i in range(1,7):
        e=meta['slots'][str(i)];case=small/f'slot-{i}';case.mkdir();raw[i]={}
        with zipfile.ZipFile(OUT/e['file'])as z,z.open('matched-heldout-proof.tar')as member,tarfile.open(fileobj=member,mode='r:')as t:
            for m in t:
                if not m.isfile():continue
                key=m.name.removeprefix('receipt/')
                if key.startswith('native/'):
                    digest=Path(key).stem;need(re.fullmatch('[a-f0-9]{64}',digest) is not None,'bad sealed native identity');data=t.extractfile(m).read();net=hashlib.sha256(data).hexdigest();dest=pool/(digest+'.zst')
                    if not dest.exists():dest.write_bytes(data)
                    if sha(dest)!=net:
                        # Alternate lossless encodings are permitted when their decompressed payload is identical.
                        check=subprocess.check_output(['zstd','-q','-d','-c',dest]);need(hashlib.sha256(check).hexdigest()==digest and hashlib.sha256(subprocess.check_output(['zstd','-q','-d','-c'],input=data)).hexdigest()==digest,'non-identical alternate native material')
                    native[digest]={'compressed_sha256':sha(dest),'bytes':dest.stat().st_size}
                if key.endswith('/clock.json') or key.startswith('meter/calibration/native-')and key.endswith('.json')or key in ('hardware-confirmation.json','heldout-worker.json'):
                    data=t.extractfile(m).read();dest=case/key;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);raw[i][key]=hashlib.sha256(data).hexdigest()
    for n in ('github-provenance.json','reopened-with-execution.json','reader-identity.json','COMPACT-SHA256','SHA256SUMS'):shutil.copyfile(OUT/n,small/n)
    save(small/'raw-event-sha256.json',raw);save(small/'native-pool.json',native);shutil.copyfile(OUT/'ruff-27470-confirmation-raw-controls.tar.gz',archive/'ruff-27470-confirmation-raw-controls.tar.gz');shutil.copyfile(OUT/'COMPACT-SHA256',archive/'COMPACT-SHA256');save(pool/'NATIVE.json',native);print('verified',len(native),'distinct original native bodies and all six complete controls',flush=True)

if __name__=='__main__':
    if sys.argv[1]=='acquire':acquire()
    elif sys.argv[1]=='package':package()
    else:raise ValueError('unsupported reader action')
