"""Verify the original typed verdicts and reconstruct the four complete native executables."""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
import read_native, elf_gate

def load(p):return json.loads(p.read_bytes())
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()

def unpack(hist,temp):
    p=HERE/'images';m=load(p/'manifest.json');base=m['base'];source=hist/'images'/(base['sha256']+'.zst')
    assert sha(source)==base['archive'] and base['reference'] is None and len(m['images'])==4
    reference=temp/base['sha256']
    with reference.open('xb')as out:subprocess.run(['zstd','-qdc',source],stdout=out,check=True)
    assert sha(reference)==base['sha256'] and reference.stat().st_size==base['size']
    for row in m['images']:
        key=row['sha256'];p2=p/(key+'.zst');dst=temp/key
        assert row['reference']==base['sha256'] and sha(p2)==row['archive'] and p2.stat().st_size==row['archive_size']
        with dst.open('xb')as out:subprocess.run(['zstd','-qdc','--long=28','--patch-from='+str(reference),p2],stdout=out,check=True)
        assert sha(dst)==key and dst.stat().st_size==row['size']

def verify(history):
    stable=HERE/'original-records.zip';orig=load(HERE/'independent-original.json');terminal=load(HERE/'terminal-original.json');proof=load(HERE/'admitted-original.json')
    assert sha(HERE/'independent-original.json')==proof['independent'] and proof['raw']=='2560c343601f78dba0aa777ca2af304ba849e835da58495c7db3436ec8355886'
    assert terminal['pass'] and not terminal['refusals'] and not terminal['errors'] and not terminal['scored']
    with tempfile.TemporaryDirectory()as td:
        t=Path(td);assert shutil.disk_usage(t).free>3<<30
        unpack(history,t);current=read_native.main(stable,sha(stable),t)
        assert current.pop('archive_sha256')==sha(stable) and orig.pop('archive_sha256')==proof['raw'] and json.loads(json.dumps(current))==orig
        assert len(current['native_stages'])==12 and len(current['sections'])==4 and len(current['raw_owners'])==6 and current['invalid']=={'P':'E0308','C':'E0308'}
        assert proof['passed'] and proof['native_cli_checks']==48 and proof['role_elfs']==current['native_stages']
        for role,phases in terminal['roles'].items():
            for name,row in phases.items():
                assert row['sha256']==phases['fully-empty-'+row['state']]['sha256'] and len(row['probes'])==4
        cwd=Path.cwd();cross={}
        try:
            os.chdir(t)
            for name in ('fully-empty-buggy','fully-empty-fixed'):
                a,b=[terminal['roles'][r][name]for r in ('P','C')]
                result=elf_gate.compare(Path(a['sha256']),Path(b['sha256']),a['native_out_dir'],b['native_out_dir'])
                # The raw renderer prints its input filename on its first, separately checked line.
                # The original used the absolute name inside tempfile.TemporaryDirectory(dir=case.ROOT).
                # This replay uses fixed relative SHA names, making the entire raw text reproducible.
                before=copy.deepcopy(terminal['cross_role'][name]);after=copy.deepcopy(result)
                for kind in ('info','macro'):
                    for i,r in enumerate(('P','C')):
                        old=before['dwarf'][kind][i];new=after['dwarf'][kind][i]
                        assert old.pop('raw')!=new.pop('raw')
                        first=f'/home/runner/work/_temp/ohm-ruf009/tmpXXXXXXXX/{r}'
                        assert old.pop('bytes')-len(first)==new.pop('bytes')-64
                assert before==after
                cross[name]=result
        finally:
            os.chdir(cwd)
    return {'raw_acquisition':proof['raw'],'compact_native_observations':sha(HERE/'independent-original.json'),
            'sha256_standalone_admission':sha(HERE/'admitted-original.json'),'native_visits':12,'native_runtime':48,
            'owners':current['raw_owners'],'invalid':current['invalid'],'all_original_ELFs':current['native_stages'],'cross_role':cross}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    for line in (HERE/'SHA256SUMS').read_text().splitlines():
        key,name=line.split('  ',1);assert sha(HERE/name)==key
    result=verify(HERE.parent/'evidence-native-cases-41623337781')
    if (HERE/'verified.json').exists():assert result==load(HERE/'verified.json')
    a.out.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
