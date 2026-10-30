"""Walk every directed role transition under the real signed Cargo before a statistical trial."""
from pathlib import Path
import json,re
from collections import Counter
ORDER="AANNMMAMNA"

def check(rt,q,select,tool_sha,log):
    rt.room()
    dest=rt.LOG/'selector-visits';dest.mkdir()
    q.acquire(dest,rt.ROOT/'seed')
    previous=None
    namespaces={}; output=[]
    normal=q.COMMAND
    q.COMMAND=[('ruff_text_size' if arg=='ruff_python_ast' else arg) for arg in normal]
    assert q.COMMAND.count('ruff_text_size')==1 and q.COMMAND.count(rt.TARGET)==1
    try:
        for i,role in enumerate(ORDER,1):
            select(role)
            path=dest/(f'{i:02d}-'+role)
            call, observed=q.command(path,rt.environment())
            events, roster, dirty, _=q.typed(call.stdout,True)
            selected,=[row for row in events if row['target']['name']=='ruff_text_size']
            rmeta,=[Path(n) for n in selected['filenames'] if n.endswith('.rmeta')]
            rlib,=[Path(n) for n in selected['filenames'] if n.endswith('.rlib')]
            found,=re.findall(r'/(v2-[0-9a-f]{16})/',str(rmeta))
            assert rmeta.is_file() and rlib.is_file()
            bmeta=rmeta.read_bytes();blib=rlib.read_bytes()
            metadata=q.custody(bmeta,'.rmeta');archive=q.custody(blib,'.rlib')
            assert namespaces.setdefault(role,found)==found
            assert all('/'+found+'/' in v['argv'][v['argv'].index('--out-dir')+1] for v in observed['rustcs'] if v['crate']=='ruff_text_size')
            output.append({'from':previous,'role':role,'actual':found,'directory':str(rmeta.parent),'rmeta':metadata,'rlib':archive,
                           'physical_rustcs':[r['crate'] for r in observed['rustcs']],'true_cargo':observed['cargo'][0],'native_stream':tool_sha(path/'native.json'),
                           'trace':tool_sha(path/'exec.tar.gz'),'files':len(roster),'dirty':dirty,'selector':log[-1]})
            previous=role
    finally:q.COMMAND=normal
    assert Counter(ORDER[j:j+2] for j in range(len(ORDER)-1))==Counter(a+b for a in 'ANM' for b in 'ANM')
    assert len(set(namespaces.values()))==3
    q.park('unscored-selector-validation')
    return {'namespaces':namespaces,'sequence':ORDER,'visits':output}
