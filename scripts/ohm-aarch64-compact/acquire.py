"""Open only the two immutable products of the named native bootstrap run."""
import hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path
import sys
repo="astral-experiments/ohm"; run="41062797687"; head="1492f034289a806c96070b23f732b33e7b95be79"
root=Path(os.environ["QA_ROOT"]); dst=root/"inputs";rec=root/"receipts"
def get(s):return subprocess.check_output(["gh","api","repos/"+repo+"/"+s])
def write(p,b):
    with p.open("xb")as f:f.write(b)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    assert os.environ['GITHUB_REPOSITORY']==repo
    wf=json.loads(get("actions/runs/"+run));assert (wf['head_sha'],wf['status'],wf['conclusion'])==(head,'completed','success')
    arts=json.loads(get("actions/runs/"+run+"/artifacts"))['artifacts'];store={}
    assert {a['name'] for a in arts}=={'gnu-compact-input-compiler-pair','gnu-compact-input-native'}
    for a in arts:
        assert not a['expired'] and 0<a['size_in_bytes']<768*2**20 and shutil.disk_usage(dst).free>a['size_in_bytes']+16*2**30
        p=dst/(a['name']+'.zip')
        with p.open('xb') as f:subprocess.run(['gh','api','repos/'+repo+'/actions/artifacts/'+str(a['id'])+'/zip'],stdout=f,check=True)
        assert p.stat().st_size==a['size_in_bytes'] and 'sha256:'+sha(p)==a['digest']
        store[a['name']]={k:a[k] for k in ('id','name','digest','size_in_bytes')}
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():assert not Path(n).is_absolute() and '..' not in Path(n).parts
            if a['name'].endswith('compiler-pair'):
                assert z.namelist()==['linux-aarch64-sdk-pair.tar.zst']
                with z.open(z.namelist()[0]) as src,(dst/'sdk.tar.zst').open('xb') as out:shutil.copyfileobj(src,out,2**20)
            else:z.extractall(dst/'native')
    native=dst/'native'; cap=json.loads((native/'sdk-custody.json').read_bytes())
    assert (native/'qa-head').read_text().strip()==head and cap['sha256']==sha(dst/'sdk.tar.zst')
    assert (native/'x86-host-run-make-pass').read_text().strip()=='a6c35ad01a98c6bef60b0a1d1af5b94c6433aaf8'
    write(dst/'key',(cap['sha256']+'\n').encode())
    write(rec/'ingress.json', (json.dumps({'run':run,'source':head,'artifacts':store,'capsule':cap},indent=2,sort_keys=True)+'\n').encode())
if __name__=='__main__':main()
