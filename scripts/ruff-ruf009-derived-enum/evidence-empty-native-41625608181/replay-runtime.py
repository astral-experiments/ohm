"""Run the four authenticated complete x86-64 Ruff executables on the original four examples."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import verify

def main():
    terminal=verify.load(HERE/'terminal-original.json'); rows=[]
    with tempfile.TemporaryDirectory()as td:
        folder=Path(td); assert shutil.disk_usage(folder).free>2<<30
        verify.unpack(HERE.parent/'evidence-native-cases-41623337781',folder)
        for role in ('P','C'):
            for state in ('buggy','fixed'):
                stage=terminal['roles'][role]['fully-empty-'+state];exe=folder/stage['sha256']
                exe.chmod(0o700);assert verify.sha(exe)==stage['sha256']
                for name,record in sorted(stage['probes'].items()):
                    args=[exe,'check','--isolated','--no-cache','--select','RUF009','--output-format=json','--stdin-filename=case.py','-']
                    actual=subprocess.run(args,cwd=folder,input=record['input'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
                    assert actual.returncode==record['code'] and actual.stderr==record['stderr']==''
                    output=actual.stdout.strip();seen=json.loads(output);expected=json.loads(record['stdout'])
                    assert len(seen)==len(expected)==actual.returncode
                    if seen:
                        assert seen[0]['filename']==str(folder/'case.py') and expected[0]['filename']=='/home/runner/work/ohm/ohm/ruff/case.py'
                        assert output.count(seen[0]['filename'])==1
                        output=output.replace(seen[0]['filename'],expected[0]['filename'])
                    assert output==record['stdout']
                    rows.append([role,state,stage['sha256'],name,actual.returncode,hashlib.sha256(output.encode()).hexdigest()])
    assert len(rows)==16
    print(json.dumps(rows,sort_keys=True,indent=2))

if __name__=='__main__':main()
