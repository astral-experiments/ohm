"""Read query-key/virtual event associations from a MeasureMe v9 stream."""
import collections,functools,gzip,json,struct

META=100_000_001
REGULAR=100_000_003
VX=struct.Struct("<QQ")
EV=struct.Struct("<QQIIII")

def need(ok,message):
    if not ok:raise ValueError(message)

def parse_profile(path,requested=None):
    """Read selected virtual-ID mappings plus metadata. Event records supply an independent observation."""
    selected=None if requested is None else frozenset(requested)|{META}
    addresses={};counts=collections.Counter();data=bytearray();tail={0:b'',2:b''};heads=set()
    headers=(b'MMES',b'MMSD',b'MMSI');version=struct.pack('<I',9)
    with gzip.open(path,'rb')as raw:
        need(raw.read(8)==b'MMPD'+version,'MeasureMe v9 file header')
        while (head:=raw.read(5)):
            need(len(head)==5,'truncated page');tag,n=struct.unpack('<BI',head);need(tag in (0,1,2)and n<=262144,'known stream and valid page length')
            b=raw.read(n);need(len(b)==n,'full page')
            if tag not in heads:
                need(b.startswith(headers[tag]+version),'measureme stream header');heads.add(tag)
                if tag!=1:b=b[8:]
            if tag==1:data.extend(b);continue
            record=EV if tag==0 else VX;chunk=tail[tag]+b;end=len(chunk)-len(chunk)%record.size;tail[tag]=chunk[end:]
            for row in record.iter_unpack(memoryview(chunk)[:end]):
                if tag==2:
                    idx,addr=row
                    if selected is None or idx in selected:
                        # Idempotent repeats are valid. A different allocation may describe the same
                        # semantic key; keep every concrete offset until its full text is decoded.
                        addresses.setdefault(idx,[]).append(addr)
                else:
                    kind,idx,*_=row
                    if idx<META and(selected is None or idx in selected):counts[idx,kind]+=1
    need(heads=={0,1,2}and all(not s for s in tail.values()),'all complete streams')
    @functools.lru_cache(maxsize=100000)
    def resolve(addr,depth=0):
        need(8<=addr<len(data)and depth<=100,'valid string address and bounded nesting');parts=[];i=addr;start=i
        while i<len(data):
            val=data[i]
            if val==255:parts.append(bytes(data[start:i]));return b''.join(parts)
            if val==254:
                need(i+9<=len(data),'complete string reference');parts.append(bytes(data[start:i]));idx=struct.unpack_from('<Q',data,i+1)[0]
                need(idx>=REGULAR,'fixed concrete string reference');parts.append(resolve(idx-REGULAR,depth+1));i+=9;start=i
            else:i+=1
        raise ValueError('unterminated measureme string')
    mappings={}
    for idx,locations in addresses.items():
        values={resolve(addr).decode('utf-8')for addr in locations};need(len(values)==1,('conflicting virtual ID',idx,values));mappings[idx]=values.pop()
    metadata=json.loads(mappings.pop(META));events={}
    for (idx,kind),n in counts.items():
        need(kind>=REGULAR,'event kind must be a concrete named category');events.setdefault(idx,{})[resolve(kind-REGULAR).decode()]=n
    return metadata,mappings,events
