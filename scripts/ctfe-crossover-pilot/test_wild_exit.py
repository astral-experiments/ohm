"""Exercise both observed outcomes on complete original, source-bound GNU link ledgers."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE),str(HERE/'kernel-review')]
from read_events import parse
from wild_fork import STOCK, finish


def refused(action):
    try:
        action()
    except (ValueError, KeyError, AssertionError):
        return
    raise ValueError('accepted changed fork or terminal evidence')


def derive(raw):
    closed=parse(raw,expected_code=0,expected_schema=3)
    native, = (x for x in closed['execs'] if x['image']['sha256']==STOCK)
    row=dict(lifetime=native['lifetime'],event=native['ordinal'],pid=native['pid'],
             argv=native['argv'],output=native['argv'][native['argv'].index('-o')+1],
             rustc_event=None,rustc_crate=None)
    return closed,row

def check(name, expected, threads):
    raw=gzip.decompress((HERE/'enrollment'/(name+'-wild-v3.tsv.gz')).read_bytes())
    closed,row=derive(raw)
    group,=finish(raw,closed,[row])
    assert group['closure']==expected and len(group['workers'])==threads
    assert bool(group['parked'])==(expected=='parked')
    for key,val in [('pid',row['pid']+1),('lifetime',row['lifetime']+1),('output','wrong'),
                    ('event',row['event']+1),('argv',row['argv']+['-o','elsewhere'])]:
        refused(lambda:finish(raw,closed,[dict(row,**{key:val})]))
    lines=raw.splitlines(keepends=True)
    for tag,life in [(b'T',group['helper']),(b'X',group['workers'][0]),(b'B',group['workers'][-1])]:
        i,=(i for i,l in enumerate(lines) if l.startswith(tag+b'\t'+str(life).encode()+b'\t'))
        changed=b''.join(lines[:i]+lines[i+1:])
        refused(lambda:finish(changed,parse(changed,expected_code=0,expected_schema=3),[row]))
    if expected=='reaped-before-helper-exit':
        # This other terminal ordering is valid for a general process trace. The stronger
        # individual-exit proof requires every worker's final wait before the helper starts its exit.
        i,=(i for i,l in enumerate(lines) if l.startswith(b'T\t'+str(group['workers'][0]).encode()+b'\t'))
        end,=(i for i,l in enumerate(lines) if l.startswith(b'X\t'+str(group['helper']).encode()+b'\t'))
        assert i<end
        rearranged=lines.copy();late=rearranged.pop(i);rearranged.insert(end,late)
        changed=b''.join(rearranged)
        alternate=parse(changed,expected_code=0,expected_schema=3)
        refused(lambda:finish(changed,alternate,[row]))
    return hashlib.sha256(raw).hexdigest(),group['closure'],len(group['workers'])

def entry(mode):
    """Run the worker through its first ordinary Cargo enrollment before activating an SDK."""
    import pilot

    boot = '0fed30e8-e9a8-4b68-be75-81585c4107ea'
    cpus = list(range(8))
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp)
        (out/'sdk').mkdir()
        for arm in ('E', 'D'):
            pilot.save(out/'sdk'/(arm+'.json'), {'files': {}})
        env = dict(GITHUB_RUN_ID='7', GITHUB_SHA='a'*40, CONTACT_RUN='',
                   CONTACT_SHA256='', CONTACT_READBACK_SHA256='')
        if mode == 'full-pilot':
            prior = out/'prior-v3-contact.json'
            pilot.save(prior, dict(official=dict(run=1, files=[dict(sha256='b'*64)]), head=env['GITHUB_SHA'],
                                   boot='1fed30e8-e9a8-4b68-be75-81585c4107ea', qualified=True))
            pilot.save(out/'meter-ready.json', dict(boot=boot, affinity=cpus))
            env.update(CONTACT_RUN='1', CONTACT_SHA256='b'*64, CONTACT_READBACK_SHA256=pilot.sha(prior))
        class ReachedSDK(Exception):
            pass
        with (patch.dict(os.environ, env), patch.object(pilot, 'OUT', out), patch.object(pilot, 'job'),
              patch.object(pilot.shutil, 'disk_usage', return_value=SimpleNamespace(free=30*2**30)),
              patch.object(pilot.b, 'prepare_checkout'), patch.object(pilot.subprocess, 'run'),
              patch('runpy.run_path', return_value={'host': lambda *_: boot}),
              patch.object(os, 'uname', return_value=SimpleNamespace(machine='x86_64', release='7.1.4')),
              patch.object(os, 'sched_getaffinity', return_value=set(cpus)), patch.object(os, 'sched_setaffinity'),
              patch.object(pilot.subjects, 'activate', side_effect=ReachedSDK) as activation):
            try:
                pilot.main(mode, '01', out, out)
            except ReachedSDK:
                pass
            activation.assert_called_once_with('Eon', {'E': {}, 'D': {}}, out/'initial')
        position = json.loads((out/'position.json').read_bytes())
        assert position['order'] == ['Eon','Don']
        assert position['command'] == ['cargo','+ohm','build','-p','ruff','--bin','ruff',
                                       '--locked','--offline','-j4','--message-format=json']
        assert position['mode'] == mode and position['boot'] == boot

if __name__=='__main__':
    print(check('parked','parked',2))
    print(check('waited','reaped-before-helper-exit',4))
    for mode in ('contact', 'full-pilot'):
        entry(mode)
        print('Enrolled the ordinary Ruff command through the', mode, 'entry point')
