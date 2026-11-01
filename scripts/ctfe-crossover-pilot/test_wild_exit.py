"""Exercise both observed outcomes on complete original, source-bound GNU link ledgers."""
import gzip
import hashlib
from pathlib import Path
import sys

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

if __name__=='__main__':
    print(check('parked','parked',2))
    print(check('waited','reaped-before-helper-exit',4))
