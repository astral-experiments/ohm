#!/usr/bin/env python3
"""Compare collectors on an identical released-Wild, no-fork Ruff CLI link."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for option in ['run_with','reference','wild','drrun','client','output']:
        ap.add_argument(option,type=Path)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    wild=a.wild.resolve(strict=True); run=a.run_with.resolve(strict=True)
    out=(a.output/'ruff').resolve();expected=sha(a.reference)
    env={k:v for k,v in os.environ.items() if k not in ['WILD_SAVE_BASE','WILD_SAVE_DIR','WILD_SAVE_SKIP_LINKING','CARGO_MAKEFLAGS','MAKEFLAGS']}
    env['OUT']=str(out)
    rows=[]
    for i,engine in enumerate(['cachegrind','dynamorio','dynamorio','cachegrind']):
        d=a.output/str(i);d.mkdir()
        if engine=='cachegrind':
            prefix=['valgrind','--tool=cachegrind','--cache-sim=no','--branch-sim=no','--trace-children=no',
                    '--cachegrind-out-file='+str((d/'guest.%p').resolve()),'--log-file='+str((d/'vg.%p').resolve())]
        else:
            prefix=[a.drrun.resolve(),'-no_follow_children','-c',a.client.resolve(),(d/'wild.ir').resolve(),'--']
        out.unlink(missing_ok=True)
        with (d/'stdout').open('wb') as stdout,(d/'stderr').open('wb') as stderr:
            p=subprocess.Popen([run,*prefix,wild,'--','--threads=1','--no-fork','--dynamic-linker=/lib64/ld-linux-x86-64.so.2'],env=env,stdout=stdout,stderr=stderr)
            assert p.wait()==0
        assert not (d/'stdout').stat().st_size
        warnings=(d/'stderr').read_text().splitlines()
        assert all(engine=='dynamorio' and re.fullmatch(r'WARNING: (?:cannot find .*/lib(?:32|64)/(?:release|debug)/libdynamorio\.so: is this an incomplete installation\?|.* does not appear to be a valid DynamoRIO root)',w) for w in warnings),warnings
        assert sha(out)==expected
        if engine=='cachegrind':
            g,=d.glob('guest.*');v,=d.glob('vg.*')
            assert int(g.suffix[1:])==int(v.suffix[1:])==p.pid
            fields={k:val for line in g.read_text().splitlines() if ': ' in line for k,val in [line.split(': ',1)]}
            assert fields['events']=='Ir' and fields['cmd'].split()[0]==str(wild)
            log=v.read_text();assert log.count(' I refs:')==1 and 'Process terminating' not in log
            count=int(fields['summary']);assert count==int(log.split(' I refs:')[1].strip().replace(',',''))
        else:
            items=[x.split() for x in (d/'wild.ir').read_text().splitlines()];pid=str(p.pid)
            assert items[0]==['B',pid,'0','0'] and items[-1]==['P',pid,'0','0']
            assert all(len(x)==4 and x[1]==pid and x[0] in ['B','P','T','F','S'] for x in items)
            assert sorted(x[2] for x in items if x[0]=='T')==sorted(x[2] for x in items if x[0]=='F')
            count=sum(int(x[3]) for x in items if x[0]=='F')
        assert count>0
        rows.append(dict(index=i,engine=engine,guest_instructions=count,output_sha256=expected))
        print(i,engine,count,flush=True)
    (a.output/'calibration.json').write_text(json.dumps({'counts':rows,'inputs':{k:sha(v) for k,v in {'run_with':run,'wild':wild,'drrun':a.drrun,'client':a.client}.items()}},indent=2)+'\n')
    out.unlink()

if __name__=='__main__':main()
