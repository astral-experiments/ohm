"""Separate actual provider invocations from the profiler formatting query names after compilation."""
import collections
import functools
import gzip
import io
import struct
from measureme import EV,REGULAR

def pages(blob):
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as data:
        assert data.read(8)==b'MMPD\x09\0\0\0'
        while tag:=data.read(5):
            stream,size=struct.unpack('<BI',tag);content=data.read(size);assert len(content)==size and size<=262144
            yield stream,content

def partition(blob,selected,sentinel):
    strings=b''.join(v for tag,v in pages(blob) if tag==1)
    @functools.lru_cache(None)
    def literal(i):
        i-=REGULAR;start=i;parts=[];assert 8<=i<len(strings)
        while i<len(strings):
            if strings[i]==255:return b''.join([*parts,strings[start:i]]).decode('utf-8')
            if strings[i]==254:
                parts.append(strings[start:i]);parts.append(literal(struct.unpack_from('<Q',strings,i+1)[0]).encode());i+=9;start=i
            else:i+=1
        raise ValueError('unterminated profile label')
    windows=[];timers=[];first=True;tail=b''
    for tag,v in pages(blob):
        if tag!=0:continue
        if first:assert v[:8]==b'MMES\x09\0\0\0';v=v[8:];first=False
        v=tail+v;n=len(v)//EV.size*EV.size;tail=v[n:]
        for kind,idx,thread,lo1,lo2,hi in EV.iter_unpack(memoryview(v)[:n]):
            if idx not in selected and idx<REGULAR:continue
            start=lo1+((hi>>16)<<32);end=lo2+((hi&65535)<<32)
            if end>=(1<<48)-2:continue
            if idx in selected and literal(kind)=='Query':timers.append((idx,start,end,thread))
            elif idx>=REGULAR and literal(kind)=='GenericActivity' and literal(idx)=='self_profile_alloc_query_strings':windows.append((start,end,thread))
    assert first is False and not tail and len(windows)==1,windows
    begin,finish,_=windows[0]
    out=collections.defaultdict(list)
    for idx,lo,hi,_ in timers:
        assert lo<=hi
        out[idx].append('before' if hi<=begin else 'after' if lo>=finish else 'during_or_overlapping')
    statuses=collections.Counter()
    for idx in selected:
        hits=out[idx]
        statuses['no_provider_event' if not hits else '+'.join(sorted(set(hits)))]+=1
    return {'queried':len(selected),'event_classification':dict(statuses),'sentinel':out[sentinel],'formatting_interval':windows[0],'provider_events':len(timers)}
