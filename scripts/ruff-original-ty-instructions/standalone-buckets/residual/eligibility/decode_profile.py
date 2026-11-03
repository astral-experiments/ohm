"""Read the two independent payloads of measureme 12's v9 RawEvent."""
import argparse,collections,functools,hashlib,json,struct
from pathlib import Path
VERSION=(9).to_bytes(4,'little')
INTEGER=0xfffffffffffe
STAGES={'monomorphization_collector','cgu_partitioning','cgu_partitioning_place_items','cgu_partitioning_split_large_cgus','cgu_partitioning_merge_cgus','cgu_partitioning_internalize_symbols','collect_and_partition_mono_items','LLVM_module_codegen','LLVM_module_codegen_emit_obj','LLVM_module_optimize','rustc_main','run_compiler'}
def decode(raw):
    assert 8<len(raw)<128*1024**2 and raw[:8]==b'MMPD'+VERSION
    streams=[bytearray()for _ in range(3)];pos=8
    while pos<len(raw):
        assert pos+5<=len(raw);tag,length=struct.unpack_from('<BI',raw,pos);pos+=5
        assert tag<3 and 0<length<=len(raw)-pos;streams[tag].extend(raw[pos:pos+length]);pos+=length
    events,strings,index=streams;assert [x[:8]for x in streams]==[k+VERSION for k in (b'MMES',b'MMSD',b'MMSI')]
    offsets=dict(struct.iter_unpack('<QQ',index[8:]));seen=set()
    @functools.lru_cache(None)
    def word(k):
        p=offsets.get(k)if k<100000003 else k-100000003
        if p is None:return b'<unresolved>'
        assert 8<=p<len(strings)and k not in seen;seen.add(k);b=bytearray()
        while p<len(strings)and strings[p]!=255:
            if strings[p]==254:
                assert p+9<=len(strings);b.extend(word(struct.unpack_from('<Q',strings,p+1)[0]));p+=9
            else:b.append(strings[p]);p+=1
            assert len(b)<4*1024**2
        assert p<len(strings);seen.remove(k);return bytes(b)
    metadata=json.loads(word(100000001));sizes={};times=collections.defaultdict(list);kinds=collections.Counter()
    for kind,key,thread,l,h,v in struct.iter_unpack('<QQIIII',events[8:]):
        label=word(kind).decode();parts=word(key).decode().split('\x1e');lo=l|((v&0xffff0000)<<16);hi=h|((v&0xffff)<<32)
        if parts[0]=='codegen_unit_size_estimate':
            assert hi==INTEGER and len(parts)==2 and 0<lo<2**40 and parts[1]not in sizes,(label,parts,lo,hi)
            sizes[parts[1]]={'size':lo,'kind':label,'thread':thread}
        if hi<INTEGER:
            assert lo<=hi;kinds[label]+=1
            if parts[0]in STAGES:
                assert label=='GenericActivity';times[parts[0]].append({'args':parts[1:],'thread':thread,'start':lo,'end':hi,'ir':hi-lo})
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'counter':metadata['counter'],'metadata':metadata,'sizes':sizes,'activities':times,'interval_kinds':kinds}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('profile',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    ans=decode(a.profile.read_bytes());a.output.write_text(json.dumps(ans,indent=2,sort_keys=True)+'\n');print('size entries',len(ans['sizes']),'activities',sorted(ans['activities']))
