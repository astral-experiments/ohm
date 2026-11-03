"""Verify registered native/PMU originals on a separate fresh host."""
from pathlib import Path
import json
import os
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import artifacts
import review

def main(phase):
    root=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    run=int(os.environ['GITHUB_RUN_ID']);out=root/'ruf009-reviewed';out.mkdir()
    nums=[0] if phase=='pilot' else list(range(1,9)) if phase=='confirmation' else []
    review.need(nums,'bad phase')
    rows=[]
    for num in nums:
        with tempfile.TemporaryDirectory(dir=root)as tmp:
            src,archive=artifacts.download(run,f'ruf009-{phase}-{num}-{run}',Path(tmp))
            try:item=review.block(src)
            except Exception as exc:
                (out/f'{phase}-{num}-failure.json').write_text(json.dumps({'original':archive,'error':repr(exc)},indent=1)+'\n')
                raise
            w=item['worker']
            review.need(w['recipe']==artifacts.recipe(),'independent checkout differs from the acquiring recipe')
            review.need((w['run'],w['sha'],w['phase'],w['block'])==(run,os.environ['GITHUB_SHA'],phase,num),'unexpected worker original')
            item['original_archive']=archive
            (out/f'{phase}-{num}.json').write_text(json.dumps(item,indent=1,sort_keys=True)+'\n')
            rows.append(item)
    if phase=='confirmation':
        result=review.aggregate(rows);(out/'aggregate.json').write_text(json.dumps(result,indent=1,sort_keys=True)+'\n')
        print(json.dumps(result,sort_keys=True))
    else:print('Pilot eligibility, reduction and original',item['pilot_admits'],item['reduction'],archive)

if __name__=='__main__':main(sys.argv[1])
