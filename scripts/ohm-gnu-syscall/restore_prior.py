"""Restore the already bootstrapped driver only after checking the original immutable run."""
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bootstrap import rt,restore

RUN=41099028701
HEAD='c71a26fb0701aef9ecdf271016a9fadb68719aa0'
ART=12998240646
DIGEST='fa5388700659b098f512e09d9093a36f50848ccd0e2ebebdb3e1216340962191'
DRIVER='d38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084'
def main():
    root='repos/astral-experiments/ohm/actions/'
    fetch=lambda url:json.loads(subprocess.check_output(['gh','api',root+url]))
    assert fetch('runs/'+str(RUN))['head_sha']==HEAD
    meta=fetch('artifacts/'+str(ART))
    assert not meta['expired'] and meta['workflow_run']['id']==RUN and meta['digest']=='sha256:'+DIGEST
    assert (meta['name'],meta['size_in_bytes'])==('gnu-literal-svc-driver',34671280)
    with tempfile.TemporaryDirectory(dir=rt.ROOT) as temp:
        d=Path(temp);repo=d/'source.zip'
        with repo.open('xb') as f:subprocess.run(['gh','api',root+'artifacts/'+str(ART)+'/zip'],stdout=f,check=True)
        assert repo.stat().st_size==meta['size_in_bytes'] and rt.sha(repo)==DIGEST
        with zipfile.ZipFile(repo) as z:
            assert sorted(z.namelist())==['candidate.json','driver.so.zst']
            z.extractall(d)
        assert json.loads((d/'candidate.json').read_text())['driver'][0]==DRIVER
        restore(d)
    rt.save(rt.LOG/'original-compiler-artifact.json',{'run':RUN,'head':HEAD,'artifact':ART,'sha256':DIGEST,'driver':DRIVER})
if __name__=='__main__':main()
