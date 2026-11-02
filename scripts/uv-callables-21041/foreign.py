"""Repeat both source-owned ABI witnesses on the exact two benchmark compiler distributions."""
import hashlib,json,subprocess,sys
from pathlib import Path
import core as c
m=c.m
def gate():
    w,tmp=c.host();pool=tmp/'ctfe22-root-sdks';ctrl,child=c.ROLES
    expected=[c.PAIR['arms'][r]['source']['commit'] for r in c.ROLES]
    for script,fixture,label in [('transition.py','fixture','coroutine-transition'),('foreign-transition.py','callable-fixture','foreign-transition')]:
        out=w/'trait-results/intake'/label
        subprocess.run([sys.executable,'-ISB',c.HERE/script,pool/ctrl,pool/child,c.HERE/fixture,out],check=True,timeout=240)
        j=m.read(out/'passed.json');c.guard(not j['self_check']and all(expected[i][:9] in j['banners'][k]for i,k in enumerate(['control','candidate'])),'wrong actual compiler identities')
        c.guard(len(j['modes'])==4,'missing two-way mixed versions')
        for name,vs in j['modes'].items():
            shared=name.endswith('-shared');c.guard(len(vs)==7 and vs[2]['asserted_incremental_state']==('loaded'if shared else'not-loaded'),'failed mixed cache switches')
            c.guard((vs[1]['active_session'].split('/')[0]==vs[2]['active_session'].split('/')[0])==shared,'actual prior crate root')
            c.guard(vs[2]['binary']==vs[3]['binary']==vs[5]['binary'] and vs[4]['commands']['reader']['codes']==vs[6]['commands']['reader']['codes']==['E0061'] and vs[4]['commands']['reader']['stderr_sha256']==vs[6]['commands']['reader']['stderr_sha256'],'changed diagnostics or linked output')
            if label=='foreign-transition':
                for n in ('roster','facade'):
                    dig=vs[2]['commands'][n]['rmeta'];c.guard(len(dig)==64 and dig==vs[3]['commands'][n]['rmeta']==vs[5]['commands'][n]['rmeta'],'changed upstream metadata')
