"""Apply the service and custody cap before Actions uploads one final artifact."""
from pathlib import Path
import os,sys,zlib

def estimate(files):
    size=65536
    for p in files:
        size+=1024+2*len(str(p).encode());codec=zlib.compressobj(1,wbits=-15)
        with p.open('rb')as f:
            while chunk:=f.read(1<<20):size+=len(codec.compress(chunk))
        size+=len(codec.flush())
    return size

if __name__=='__main__':
    import json
    root=Path('trait-results');files=sorted(f for f in root.rglob('*')if f.is_file());estimate_bytes=estimate(files);full=estimate_bytes+(8<<20)<638<<20
    (root/'archive-budget.json').write_text(json.dumps({'complete_collection':full,'deflate_level_1_estimate':estimate_bytes,'members':len(files),'service_cap':768<<20,'custody_original_cap':638<<20},sort_keys=True)+'\n')
    choice=['trait-results/']if full else ['trait-results/archive-budget.json','trait-results/uv-client/raw-pairs.json','trait-results/uv-client/wall-tail-score.json','trait-results/uv-client/opening-*/warm-B/ordinary.json','trait-results/uv-client/opening-*/warm-B/resources.json','trait-results/uv-client/opening-*/warm-B/cargo.stderr','trait-results/*.log']
    with Path(os.environ['GITHUB_OUTPUT']).open('a')as f:f.write('selected<<PAYLOAD\n'+'\n'.join(choice)+'\nPAYLOAD\n')
    if not full:raise SystemExit('complete original exceeds its conservative archive allowance; retain all ordinary clocks and raw resources as a refused intake')
