"""Reopen a two-SDK worker's native process streams and each captured user rmeta."""
import argparse
import hashlib
import json
from pathlib import Path

def sha(b):
    return hashlib.sha256(b).hexdigest()

def header(b):
    assert b[:8] == b'rust\x00\x00\x00\n'
    n = 0
    for i,x in enumerate(b[16:22]):
        n |= (x & 127) << (7*i)
        if x < 128:
            start = 17+i
            return b[start:start+n].decode('utf8')
    raise AssertionError('invalid compiler version')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('work',type=Path)
    args=p.parse_args();w=args.work;r=w/'raw'
    terminal=(w/'completed.json').read_bytes();j=json.loads(terminal)
    assert j['fresh_user_cross_rejected'] is True
    assert j['compiler_versions']['old']==j['compiler_versions']['new']
    commands={x['label']:x for x in j['commands']}
    assert len(j['commands'])==len(commands)==22
    for lab,x in commands.items():
        for name in ('stdout','stderr'):
            assert sha((r/lab/name).read_bytes())==x[name],(lab,name)
        assert x['exit']==(1 if lab.startswith('reject-user-') else 0),lab
    for arm in ('old','new'):
        assert (r/('tool-'+arm)/'stdout').read_text()==j['compiler_versions'][arm]
        d=commands['reject-user-'+arm]; assert d['arm']!=arm
        errors=[json.loads(b) for b in (r/d['label']/'stderr').read_bytes().splitlines() if b.startswith(b'{')]
        assert any(x.get('level')=='error' and (x.get('code') or {}).get('code')=='E0514' and 'subject' in x['message'] for x in errors)
    expected=[('old','train-old','not-loaded'),('old','reopen-old','loaded'),('new','switch-new','not-loaded'),('new','reopen-new','loaded'),('old','switch-old','not-loaded'),('old','reopen-old2','loaded')]
    assert [(s['arm'],s['label']) for s in j['snapshots']]==[(a,l) for a,l,_ in expected]
    epochs={'old':1,'new':2};gens={'old':8,'new':9}
    versions=set();phases=[]
    for (arm,lab,state),s in zip(expected,j['snapshots'],strict=True):
        c=commands[lab]; assert ['rustc','+ohm']==c['cmd'][:2] and '-Zassert-incr-state='+state in c['cmd']
        assert s['graph']['version']==gens[arm] and s['graph']['stamp']==j['forced_graph_stamp']
        data=(r/lab/'libsubject.rmeta').read_bytes();v=header(data);assert sha(data)==s['metadata_sha'] and v==s['metadata_version']
        suffix=f' (Ohm metadata {epochs[arm]})';assert v.endswith(suffix);versions.add(v[:-len(suffix)])
        assert commands[lab+'-reader']['cmd'][-2:]==['-o','reader'] and commands[lab+'-run']['cmd']==['./reader']
        if state=='not-loaded':assert s['prefix']
        if lab.startswith('switch'):assert b'reused metadata item prefix' not in (r/lab/'stderr').read_bytes()
        phases.append([lab,state,gens[arm],s['metadata_sha']])
    assert len(versions)==1
    print(json.dumps(dict(terminal_sha256=sha(terminal),native_commands=len(commands),executed_readers=len(expected),
        rejected_user_crates=['old read by new','new read by old'],decoded_metadata_source_stamp=versions.pop(),verified_phases=phases),indent=2))
if __name__=='__main__':main()
