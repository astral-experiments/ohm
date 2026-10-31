"""Seal a completed native run, then reopen its real artifacts by ID, SHA and source tree."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ENROLL = json.loads((HERE/'inputs/registration.json').read_text())
REPO = 'astral-experiments/ohm'
HOST = 'x86_64-unknown-linux-gnu'
CARGO = '035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
WILD = Path('lib/rustlib')/HOST/'bin/wild-ld/ld.bfd'
WILD_HASH = '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'


def need(condition, msg):
    if not condition: raise RuntimeError(str(msg))


def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')


def api(path, dest=None):
    cmd=[os.environ.get('GITHUB_CLI','gh'),'api','repos/'+REPO+'/'+path]
    if dest is None: return json.loads(subprocess.check_output(cmd))
    with dest.open('xb') as f: subprocess.run(cmd,stdout=f,check=True)


def get_blob(path, obj):
    if not path.exists(): api('actions/artifacts/'+str(obj['id'])+'/zip',path)
    need(path.stat().st_size==obj['bytes'] and sha(path)==obj['sha256'], 'wrong GitHub ZIP bytes for '+obj['name'])


def qualification(path):
    with zipfile.ZipFile(path) as z:
        files=[m for m in z.namelist() if Path(m).name=='qualification.json']
        need(len(files)==1 and z.testzip() is None,'incomplete/ambiguous native qualification')
        q=json.loads(z.read(files[0]));need(q['status']=='pass' and set(q['roles'])=={'parent','candidate','legacy'},'native gates did not qualify')
        need(all(q['roles'][r]['tree']==t for r,t in ENROLL['role_trees'].items()),'unexpected Rust source from native run')
        need(q['results']['parent']['axes']==q['results']['candidate']['axes'] and q['results']['parent']['cargo']==q['results']['candidate']['cargo'],'native behavior diverged')
        need(q['results']['parent']['targets']=={HOST:True,'custom-host':True,'aarch64-unknown-linux-gnu':True} and q['results']['candidate']['targets']=={HOST:False,'custom-host':True,'aarch64-unknown-linux-gnu':True},'native-only admission missing')
        migration=[n for n in z.namelist() if n.endswith('incremental/independent-reader/stdout')];need(len(migration)==1,'missing migration readback')
        readback=json.loads(z.read(migration[0]));need(readback['native_commands']==22 and readback['rejected_user_crates']==['old read by new','new read by old'],'native stale-epoch gate incomplete')
        return q, hashlib.sha256(z.read(files[0])).hexdigest()


def register(path, cache):
    need(not path.exists(),'the source seal already exists'); cache.mkdir(parents=True,exist_ok=True)
    run=api('actions/runs/'+str(ENROLL['native_run']))
    need(run['id']==ENROLL['native_run'] and run['head_sha']==ENROLL['native_qa'] and run['head_branch']==ENROLL['native_branch'] and run['path']=='.github/workflows/ci.yml' and run['event']=='workflow_dispatch' and run['status']=='completed' and run['conclusion']=='success' and run['repository']['full_name']==REPO,'unqualified source workflow')
    raw=api('actions/runs/'+str(run['id'])+'/artifacts?per_page=100');need(raw['total_count']==len(raw['artifacts']),'paginated artifact set')
    needed={}
    for name in ('parent','candidate','compiler-native-admission'):
        item,=[x for x in raw['artifacts'] if x['name']==name]
        receipt=item['workflow_run'];need(not item['expired'] and receipt['id']==run['id'] and receipt['head_sha']==run['head_sha'] and item['digest'].startswith('sha256:') and len(item['digest'])==71,'source artifact binding')
        needed[name]={'name':name,'id':item['id'],'bytes':item['size_in_bytes'],'sha256':item['digest'][7:],'expires':item['expires_at']}
    proof=cache/'compiler-native-admission.zip';get_blob(proof,needed['compiler-native-admission']);q,digest=qualification(proof)
    write(path,{'run':run['id'],'head':run['head_sha'],'branch':run['head_branch'],'run_attempt':run['run_attempt'],'artifacts':needed,'qualification':digest,'roles':q['roles']})


def acquire(destination, cache, seal):
    info=json.loads(seal.read_text());need((info['run'],info['head'],info['branch'])==(ENROLL['native_run'],ENROLL['native_qa'],ENROLL['native_branch']),'foreign SDK seal')
    destination.mkdir(); cache.mkdir(parents=True,exist_ok=True)
    for name,obj in info['artifacts'].items():get_blob(cache/(name+'.zip'),obj)
    q,digest=qualification(cache/'compiler-native-admission.zip');need(digest==info['qualification'] and q['roles']==info['roles'],'native qualification changed')
    for role in ('parent','candidate'):
        dest=destination/role;dest.mkdir();record=info['roles'][role]
        with zipfile.ZipFile(cache/(role+'.zip')) as z:
            need(set(z.namelist())=={'manifest.json','toolchain.tar.zst'},'unexpected source SDK ZIP');m=json.loads(z.read('manifest.json'))
            need((m['qa'],m['role'],m['tree'],m['commit'],m['transfer'])==(info['head'],role,ENROLL['role_trees'][role],record['commit'],record['transfer']),'manifest mismatch')
            archive=destination/(role+'.tar.zst')
            with z.open('toolchain.tar.zst') as f, archive.open('xb') as out: shutil.copyfileobj(f,out)
        need(sha(archive)==m['transfer'],'source SDK bytes changed'); files=m['files'].copy()
        with subprocess.Popen(['zstd','-qdc',archive],stdout=subprocess.PIPE) as decoder:
            with tarfile.open(fileobj=decoder.stdout,mode='r|') as tar:
                for entry in tar:
                    p=Path(entry.name);need(entry.isfile() and not p.is_absolute() and '..' not in p.parts and entry.name in files,'unexpected SDK member')
                    digest,size,mode=files.pop(entry.name);tar.extract(entry,dest,filter='data');out=dest/p;out.chmod(mode)
                    need(sha(out)==digest and out.stat().st_size==size,'wrong acquired SDK member: '+str(p))
            need(not any(decoder.stdout.read()) and decoder.wait()==0 and not files,'incomplete SDK')
        need(sha(dest/'bin/cargo')==CARGO and sha(dest/WILD)==WILD_HASH,'different Cargo or Wild')
        write(destination/(role+'.json'),m); archive.unlink()
    write(destination/'admission.json',info)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sections=parser.add_subparsers(dest='action',required=True)
    p=sections.add_parser('register');p.add_argument('seal',type=Path);p.add_argument('cache',type=Path)
    p=sections.add_parser('acquire');p.add_argument('destination',type=Path);p.add_argument('cache',type=Path);p.add_argument('seal',type=Path)
    a=parser.parse_args(); register(a.seal,a.cache) if a.action=='register' else acquire(a.destination,a.cache,a.seal)
