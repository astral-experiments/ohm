#!/usr/bin/env python3
"""Recover the first rejected record in a source-matched 38-byte rustc dep-graph."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager

END = b'rust-end-file'
CAP = 384 << 20

@contextmanager
def original(path):
    if path.suffix != '.zst':
        with path.open('rb') as f:
            if not (0 < f.seek(0,2) <= CAP): raise ValueError('raw size outside admission')
            with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data: yield data
        return
    with tempfile.TemporaryFile(dir='/dev/shm') as f, subprocess.Popen(['zstd','-qd','-c',str(path)],stdout=subprocess.PIPE) as pr:
        size=0
        while part:=pr.stdout.read(1<<20):
            size+=len(part)
            if size>CAP:
                pr.kill(); raise ValueError('expanded size outside admission')
            f.write(part)
        if pr.wait()!=0 or size==0: raise ValueError('zstd could not reopen complete input')
        f.flush()
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data: yield data

def uleb(data, cursor):
    value=0
    for shift in range(0,70,7):
        byte=data[cursor]
        cursor+=1
        value|=(byte&127)<<shift
        if byte<128:
            return value,cursor
    raise ValueError('invalid ULEB length')

def record(data, pos, kinds):
    bits=(kinds-1).bit_length()
    head,index=struct.unpack_from('<HI',data,pos)
    count=head>>(bits+2)
    width=((head>>bits)&3)+1
    start=pos+38
    if count: length=count-1
    else: length,start=uleb(data,start)
    return {'offset':pos, 'raw_header':data[pos:pos+38].hex(), 'index':index,
            'kind':head&((1<<bits)-1), 'width':width, 'edges':length,
            'edge_data_start':start, 'end':start+length*width}

def read(data,kinds=362):
    output={'sha256':sha256(data).hexdigest(),'size':len(data),'kinds':kinds,'accepted':False}
    if data[:4]!=b'RSIC' or data[-13:]!=END:
        return output|{'failure':'file magic or end marker'}
    output['version']=struct.unpack_from('<H',data,4)[0]
    vlen=data[6];output['version_string']=data[7:7+vlen].decode('utf-8')
    graph=7+vlen+8;end=len(data)-13;footer=end-24
    maximum,n,ne=struct.unpack_from('<QQQ',data,footer)
    output['footer']={'space':maximum,'nodes':n,'edges':ne}
    stats_end=footer
    if data[footer-8:footer]==b'OHMIDX01':
        stats_end,roots=struct.unpack_from('<QQ',data,footer-24)
        if stats_end+8*maximum+4*roots != footer-24 or roots>n:
            return output|{'failure':'malformed optional seek trailer'}
    if not (n<=maximum<=8_000_000 and graph+38*n<=stats_end):
        return output|{'failure':'footer counts exceed bound'}
    seen=bytearray(maximum); used=bytearray(maximum)
    kind_counts=Counter(); lengths=Counter();widths=Counter(); total=0;p=graph;previous=None; first_bad_width=None
    for i in range(n):
        if p+38>stats_end:return output|{'failure':'header overlaps footer','ordinal':i,'previous':previous,'offset':p}
        head,idx=struct.unpack_from('<HI',data,p);k=head&((1<<(kinds-1).bit_length())-1)
        if k==0 or idx>=maximum or seen[idx] or k>=kinds:
            reason='incoming Null' if k==0 else 'out of range node index' if idx>=maximum else 'duplicate node index' if seen[idx] else 'invalid kind discriminant'
            failure={'failure':reason,'ordinal':i,'offset':p,'index':idx,'kind':k,'seen':idx<maximum and bool(seen[idx]),'raw_header':data[p:p+38].hex(),'previous':previous,'context_offset':max(graph,p-48),'context':data[max(graph,p-48):p+76].hex(),'consumed_edges':total}
            if failure['seen']:
                match=graph
                for j in range(i):
                    row=record(data,match,kinds)
                    if row['index']==idx:
                        failure['first_owner']={'ordinal':j,**row};break
                    match=row['end']
            return output|failure
        row=record(data,p,kinds);start=row['edge_data_start'];stop=row['end'];width=row['width']; length=row['edges']
        if length>0xffffffff or stop>stats_end:
            return output|{'failure':'edge list overlaps footer','ordinal':i,'record':row,'previous':previous}
        if width==1: ids=data[start:stop]
        elif width==2: ids=(v[0] for v in struct.iter_unpack('<H',data[start:stop]))
        elif width==4: ids=(v[0] for v in struct.iter_unpack('<I',data[start:stop]))
        else:ids=(int.from_bytes(data[off:off+3],'little') for off in range(start,stop,3))
        maxid=0
        for v in ids:
            if v>=maximum:return output|{'failure':'edge out of range','ordinal':i,'record':row,'edge':v}
            used[v]=1
            if v>maxid:maxid=v
        optimum=max(1,(maxid.bit_length()+7)//8)
        if width!=optimum and first_bad_width is None: first_bad_width={'ordinal':i,'record':row,'max_edge':maxid,'expected_width':optimum}
        kind_counts[k]+=1; lengths[length]+=1;widths[width]+=1; seen[idx]=1;total+=length;previous=row;p=stop
    count_start=p;arr=[]
    while p<stats_end:
        v,p=uleb(data,p);arr.append(v)
    dangling=[i for i,(a,b) in enumerate(zip(used,seen)) if a and not b]
    checks={'edge_count':ne==total,'all_edges_to_live_nodes':len(dangling)==0,
            'histogram':len(arr)==kinds+1 and arr[:-1]==[kind_counts[i] for i in range(kinds)],
            'exact_stats_end':p==stats_end,'minimal_width':first_bad_width is None}
    return output|{'accepted':all(checks.values()),'checks':checks,'graph_start':graph,'counts_start':count_start,
                   'dangling_count':len(dangling),'dangling_examples':dangling[:8],'session_count':arr[-1] if arr else None,
                   'widths':widths,'thresholds':{k:lengths[k] for k in (0,30,31,127,128)},'first_nonminimum_width':first_bad_width}

def synth():
    kinds=362;h=bytearray(b'RSIC'+struct.pack('<H',10)+b'\x01X'+bytes(8))
    positions=[]
    for k,idx in [(3,0),(1,1)]:
        positions.append(len(h));h.extend(struct.pack('<HI',k+2048,idx)+bytes(32))
    for k in range(kinds):h.append(int(k in (1,3)))
    h.extend(b'\x01'+struct.pack('<QQQ',2,2,0)+END)
    assert read(h)['accepted']
    n=h.copy();n[positions[1]:positions[1]+2]=struct.pack('<H',2048)
    d=h.copy();d[positions[1]+2:positions[1]+6]=bytes(4)
    n0,d0=read(n),read(d)
    assert n0['failure']=='incoming Null' and not n0['seen']
    assert d0['failure']=='duplicate node index' and d0['first_owner']['ordinal']==0
    return {'good':sha256(h).hexdigest(),'null':n0,'duplicate':d0}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',nargs='?',type=Path);parser.add_argument('--sha256');parser.add_argument('--kinds',type=int,default=362)
    parser.add_argument('--controls',action='store_true');args=parser.parse_args()
    if args.controls:
        print(json.dumps(synth(),sort_keys=True));sys.exit()
    if args.file is None:parser.error('provide a graph or --controls')
    with original(args.file) as data:
        result=read(data,args.kinds)
    if args.sha256 and result['sha256']!=args.sha256:parser.error('original SHA256 mismatch')
    print(json.dumps(result,sort_keys=True))
    sys.exit(0 if result['accepted'] else 1)
