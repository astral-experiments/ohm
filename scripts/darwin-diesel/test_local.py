"""Exercise the real custody and four-reader control paths with tiny local scratch data."""

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import graphs
import worker


def check():
    with tempfile.TemporaryDirectory(prefix='diesel-reader-check-') as t:
        root=Path(t)
        result=root/'reports/parent-observed'; result.mkdir(parents=True)
        stage=root/'parent-observed'
        cwd=stage/'tmp/.tmp-demo'; cwd.mkdir(parents=True)
        file=cwd/worker.Q; file.parent.mkdir(parents=True)
        for label in ('A','B'):
            (result.parent/(label+'.rs')).write_text(label+'\n')
        data={x:graphs.sha(result.parent/(x+'.rs')) for x in ('A','B')}
        graphs.put(result.parent/'inputs.json',{'source_hashes':data})
        env={'PATH':os.defpath,'OHM_DIESEL_STAGE':str(stage),'OHM_DIESEL_RESULTS':str(result),
             'RUSTC_FORCE_RUSTC_VERSION':'rustc-perf','RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER':'rustc-perf'}
        demo=root/'fixture'
        demo.write_text('#!/bin/sh\nwhile [ "$1" != --out-dir ]; do shift; done\nprintf fixture > "$2/libdiesel-test.rlib"\nprintf fixture > "$2/libdiesel-test.rmeta"\n')
        demo.chmod(0o700)
        (cwd/'out').mkdir()
        command=[str(demo),'--crate-name','diesel','-C','opt-level=3','-Zincremental-verify-ich','-Zthreads=1','--out-dir',str(cwd/'out')]
        inc=cwd/'incremental-state'
        tab=inc/'diesel-01/s-01/dep-graph.bin'
        previous=Path.cwd()
        try:
            os.chdir(cwd)
            with patch.dict(os.environ,env,clear=True):
                file.write_text('A\n')
                graphs.observe('before',-1,command)
                graphs.observe('after',0,command)
                command += ['-C','incremental='+str(inc)]
                graphs.observe('before',-1,command)
                tab.parent.mkdir(parents=True); tab.write_bytes(b'generation-one')
                graphs.observe('after',0,command)
                graphs.observe('before',-1,command)
                tab.write_bytes(b'generation-two')
                graphs.observe('after',0,command)
                file.write_text('B\n')
                graphs.observe('before',-1,command)
                graphs.observe('after',0,command)
        finally:
            os.chdir(previous)
        worker.replay(stage,result)
        rs=[json.loads((result/'controlled-readers'/s/'read.json').read_bytes()) for s in ('patched-retry','unchanged-reader','empty-A','empty-B')]
        assert [s['source'] for s in rs]==['B','A','A','B'] and [bool(s['incoming']) for s in rs]==[True,True,False,False]
        assert rs[0]['incoming']==rs[1]['incoming'] and len(list((result/'bodies').iterdir()))==2
        bad=stage/'patched-input/incremental-state/diesel-01/s-01/dep-graph.bin'
        bad.write_bytes(b'other')
        if graphs.sha(bad)==rs[0]['incoming'][0][1]:
            raise ValueError('forged graph passed')
        print('two actual graph generations, four phase captures, both source states, same-input and empty replay controls passed')


if __name__=='__main__':
    check()
