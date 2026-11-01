#!/usr/bin/env python3
"""Show the eager native node-header verdict separately from deeper edge validation.

SerializedDepGraph::decode checks kind/index and copies the raw edges. It does
not decode or bounds-check individual edges in this loop. A bad edge can precede
a later duplicate; report both rather than allowing an early offline check to
mask the native header assertion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from graph_forensics import END,original,read,record

def scan(d,kinds=362):
    assert d[:4]==b'RSIC' and d[-len(END):]==END
    stop=len(d)-len(END)-24
    maximum,n,edges=struct.unpack_from('<QQQ',d,stop)
    if d[stop-8:stop]==b'OHMIDX01':stop=struct.unpack_from('<Q',d,stop-24)[0]
    start=7+d[6]+8
    assert n<=maximum<=8_000_000 and start+38*n<=stop
    seen=bytearray(maximum);width=(kinds-1).bit_length()
    offset=start;previous=None
    for i in range(n):
        prefix={'ordinal':i,'offset':offset,'previous':previous}
        if offset+38>stop:return prefix|{'failure':'header past graph'}
        head,idx=struct.unpack_from('<HI',d,offset);k=head&((1<<width)-1)
        details=prefix|{'kind':k,'index':idx,'raw_header':d[offset:offset+38].hex()}
        if k>=kinds:return details|{'failure':'invalid DepKind discriminant'}
        if idx>=maximum:return details|{'failure':'destination index out of range'}
        if k==0 or seen[idx]:
            details.update(failure='incoming Null' if k==0 else 'duplicate node index',
                           assertion='serialized.rs:382',destination_previously_occupied=bool(seen[idx]))
            if seen[idx]:
                cursor=start
                for j in range(i):
                    row=record(d,cursor,kinds)
                    if row['index']==idx:
                        details['first_owner']={'ordinal':j,**row};break
                    cursor=row['end']
            return details
        seen[idx]=1;row=record(d,offset,kinds)
        if row['end']>stop:return details|{'failure':'raw packed edge bytes past graph','record':row}
        previous=row;offset=row['end']
    return {'all_node_headers_passed':True,'nodes':n,'counts_start':offset}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('file',type=Path);parser.add_argument('--sha256',required=True);parser.add_argument('--kinds',type=int,default=362)
    a=parser.parse_args()
    with original(a.file) as d:
        assert hashlib.sha256(d).hexdigest()==a.sha256
        eager=scan(d,a.kinds);deeper=read(d,a.kinds)
    print(json.dumps({'eager_headers':eager,'complete_structure':deeper},sort_keys=True))
    return 0 if eager.get('all_node_headers_passed') and deeper['accepted'] else 1

if __name__=='__main__':raise SystemExit(main())
