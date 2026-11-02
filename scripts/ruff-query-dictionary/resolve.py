"""Join signed -22 profile virtual string IDs to *this process's* current graph only."""
import argparse,collections,contextlib,functools,gzip,hashlib,json,os,re,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "ruff-cgu-inputs/cgu-probe"))
import graph

META=100_000_001
REGULAR=100_000_003
VX=struct.Struct('<QQ')
EV=struct.Struct('<QQIIII')

def need(condition,why):
    if not condition:raise ValueError(why)

def paired(directory,graph_file=None,profile_file=None):
    process=json.loads((directory/'process.json').read_bytes());files={}
    for label,override in [('graph',graph_file),('profile',profile_file)]:
        path=override or directory/(label+'.gz');receipt=process[label]
        need(graph.sha(path)==receipt['gzip_sha256'],('wrong process-bound '+label+' archive',path))
        with gzip.open(path,'rb')as f:need(hashlib.file_digest(f,'sha256').hexdigest()==receipt['sha256'],('wrong uncompressed '+label,path))
        files[label]=path
    return files,process

@contextlib.contextmanager
def graph_input(path,expected,expected_length=None):
    """Use an authenticated raw file directly, or decompress into bounded anonymous RAM."""
    if path.suffix!='.gz':
        need(graph.sha(path)==expected,'unprofiled or current raw graph digest differs from enrollment')
        yield path
        return
    if expected_length is None:
        with path.open('rb')as f:
            f.seek(-4,2);expected_length=struct.unpack('<I',f.read(4))[0]
    need(0<expected_length<1<<32,'supported single signed graph extent')
    if expected_length>16<<20:
        available=int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
        need(available>=8*(1<<30)+expected_length+(128<<20),'RAM guard: supply the already frozen uncompressed graph')
    fd=os.memfd_create('current-signed-query-graph')
    try:
        total=0;digest=hashlib.sha256()
        with gzip.open(path,'rb')as z,os.fdopen(os.dup(fd),'wb')as out:
            while chunk:=z.read(1<<20):
                total+=len(chunk);need(total<=expected_length,'graph exceeds registered extent');digest.update(chunk);out.write(chunk)
        need(total==expected_length and digest.hexdigest()==expected,'frozen uncompressed graph digest differs from enrollment')
        yield Path(f'/proc/self/fd/{fd}')
    finally:os.close(fd)

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

def probe_graph(path,rows):
    """Independently seek signed OHMIDX01 offsets and check whole node identities and values."""
    with graph.file(path)as b:
        _,end=graph.header(b);start,roots,magic,mx,n,ne=struct.unpack_from('<QQ8sQQQ',b,end-48)
        need(magic==b'OHMIDX01'and start+mx*8+roots*4==end-48,'signed per-index directory')
        for idx,r in rows.items():
            need(idx<mx,('index outside registered extent',idx));off=struct.unpack_from('<Q',b,start+idx*8)[0]
            need(0<off<start-37,('index absent from seek directory',idx,off));head,record_idx=struct.unpack_from('<HI',b,off)
            need((record_idx,head&511,graph.stable(b[off+6:off+22]),graph.stable(b[off+22:off+38]))==(idx,r['kind'],r['key'],r['value']),('seek directory different from sequential raw stream',idx))

def read(directory,keys=(),names=(),graph_file=None,profile_file=None,strict_keys=None):
    files,p=paired(directory,graph_file,profile_file);assert keys or names
    with graph_input(files['graph'],p['graph']['sha256'],p['graph']['length'])as raw:
        if keys:
            need(all(0<k<len(graph.NAMES)and re.fullmatch(r'[0-9a-f]{32}',key)for k,key in keys),'registered signed kind and canonical stable 128-bit key')
            summary,rows=graph.graph(raw,keys=keys);metadata,mapping,events=parse_profile(files['profile'],rows)
        else:
            metadata,mapping,events=parse_profile(files['profile']);indices={idx for idx,name in mapping.items() if name.split('\x1e',1)[0] in names};summary,rows=graph.graph(raw,indices=indices)
            need(set(rows)==indices,'recorded query outside the selected current graph')
        need(metadata['process_id']==p['pid'] and int(Path(p['profile_name']).stem.rsplit('-',1)[1])==p['pid'],'inner profile PID differs from enrolled compiler PID')
        need(metadata['cmd']==' '.join(p['argv'])+' ',('stated process argv differs from recorded profile',metadata['cmd'],p['argv']))
        if summary['seek_index']:probe_graph(raw,rows)
    if 'graph_alias' in p:need(summary['seek_index']==(p['graph_alias']=='ohm-check-dep-graph.bin'),'signed seek directory must only be on a check graph')
    out=[]
    for idx,r in sorted(rows.items()):
        raw=mapping.get(idx);split=[] if raw is None else raw.split('\x1e',1)
        mismatch = None
        if split and (len(split)!=2 or split[0]!=r['name']):
            mismatch=raw
            need(strict_keys is not None and (r['kind'],r['key']) not in strict_keys,('profile and graph disagree on registered query kind',idx,r['name'],split[:1]))
            split=[]
        out.append({**{k:r[k]for k in ('kind','name','index','key','value')},'item':split[1]if split else None,'unjoined_profile_label':mismatch,'events':events.get(idx,{}),'graph':p['graph']['sha256'],'profile':p['profile']['sha256'],'pid':p['pid']})
    return {'summary':summary,'rows':out,'pid':p['pid']}
