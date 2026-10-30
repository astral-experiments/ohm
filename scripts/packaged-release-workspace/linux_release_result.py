"""Reconstitute native counts, the exact 50 Linux destinations, and all differing ELF originals."""
import argparse
import functools
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import linux_reopen as observed
from linux_common import CHUNK,E2E,RUN_CASE,STEPS,SUBJECTS,digest,event,outputs
from packages import need


def complete_elf(c,role,h):
    base=role+'/portable-elfs';manifest=c.json(base+'/images/'+h+'.json');body=bytearray()
    for i,(key,n) in enumerate(manifest['chunks']):
        part=c.raw(base+'/blocks/'+key+'.gz');need(digest(part)==key and len(part)==n and (i==len(manifest['chunks'])-1 or n==CHUNK),'incorrect original ELF block')
        body.extend(part)
    need(digest(body)==h==manifest['sha256'] and len(body)==manifest['size'],'wrong complete original ELF')
    return body


def attributes(body):
    need(body[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',body,18)[0]==62,'not an x86-64 ELF')
    start,=struct.unpack_from('<Q',body,40);width,n,strings=struct.unpack_from('<HHH',body,58)
    need(width==64 and strings<n and start+n*width<=len(body),'bad ELF64 section table')
    rows=[struct.unpack_from('<IIQQQQIIQQ',body,start+i*width) for i in range(n)];s=rows[strings];ranges={};actual={}
    for i,row in enumerate(rows):
        name,ty,flags,_,lo,sz,*_=row
        need(name<s[5],'name exceeds original ELF string table');off=s[4]+name;label=body[off:body.index(0,off,s[4]+s[5])].decode()
        if label=='.note.gnu.build-id':
            ns,des,note=struct.unpack_from('<III',body,lo);begin=lo+12+((ns+3)//4)*4
            need(ty==7 and ns==4 and note==3 and body[lo+12:lo+16]==b'GNU\0' and 0<des<=64 and begin+des<=lo+sz,'unexpected GNU build-ID note')
            ranges[label]=[begin,des];actual[label]=body[begin:begin+des].hex()
        elif label=='.rodata':
            at=start+i*width+56;need(ty==1 and bool(flags&2) and struct.unpack_from('<Q',body,at)[0]==row[9],'invalid .rodata entry size')
            ranges['.rodata.sh_entsize']=[at,8];actual['.rodata.sh_entsize']=row[9];actual['.rodata.sh_flags']=flags
    need(set(ranges)=={'.note.gnu.build-id','.rodata.sh_entsize'},'expected native fields missing')
    return ranges,actual


def exceptions(c,role,q):
    @functools.lru_cache(None)
    def load(h):
        b=complete_elf(c,role,h);raw=digest(b);ranges,actual=attributes(b)
        for at,length in ranges.values():b[at:at+length]=bytes(length)
        return {'raw':raw,'size':len(b),'physical_fields':actual,'field_offsets':ranges,'rest_of_complete_ELF':digest(b)}
    result={}
    for phase,key,allocated in q['entire_file_differences_to_own_empty']:
        ref='clean-'+dict(STEPS)[phase];a=q['stages'][phase]['all_50_full_elf_sha256'][key];b=q['stages'][ref]['all_50_full_elf_sha256'][key]
        warm,empty=load(a),load(b)
        result[phase+'|'+key]={'observed':warm,'empty':empty,'differing_allocated_section_payloads':allocated,
           'entire_ELF_equal_beyond_both_fields':warm['size']==empty['size'] and warm['field_offsets']==empty['field_offsets'] and warm['rest_of_complete_ELF']==empty['rest_of_complete_ELF']}
    return result


def reconstruct(c,role,q):
    phases={};first49={k for k,v in SUBJECTS.items() if v['cold_unchanged_same']}
    for name,result in q['stages'].items():
        root=role+'/native/'+name;_,returned=outputs(c.raw(root+'/cargo.stdout.gz'));path=returned[E2E]['executable'];suffix=Path(path).name.removeprefix('e2e-')
        typed={v['pid']:v for v in result['all_physical_rustcs'] if v['crate']=='e2e'};matches=[]
        for pid,line in json.loads(c.raw(root+'/kernel.json.gz')):
            r=typed.get(pid)
            if not r or r['argv_sha256']!=digest(line.encode()):continue
            _,args=event(line.encode());cg=[v for k,v in zip(args,args[1:]) if k=='-C']+[v[2:] for v in args if v!='-C' and v.startswith('-C')]
            source=[v for v in args if ('/'+v).endswith('/crates/ty_server/tests/e2e/main.rs')]
            selected='extra-filename=-'+suffix in cg
            if source:need(selected and len(source)==1 and '--test' in args,'native ty_server compiler returned a different logical output')
            if selected:
                need(source or r['mode']=='link-only','unbound physical compiler');matches.append({**r,'observed_source':source})
        links=[v for v in result['all_physical_wild_pids'] if v['unit']==E2E]
        tests=c.raw(root+'/e2e-list.stdout.gz').decode().splitlines();positive=c.raw(root+'/e2e-case.stdout.gz');negative=c.raw(root+'/e2e-missing.stdout.gz')
        need(len(set(tests))==len(tests) and all(s.endswith(': test') for s in tests) and RUN_CASE+': test' in tests and
             ('test '+RUN_CASE+' ... ok').encode() in positive and b'0 passed; 1 failed' in negative,'wrong original e2e verdict')
        old50=set(result['historical_50_linked']);real=result['all_native_counts']
        phases[name]={'full_rustcs':real.get('full',0),'link_only_rustcs':real.get('link-only',0),'all_Wild_links':real.get('wild',0),
                'ron_rustcs':[v for v in result['all_physical_rustcs'] if v['crate']=='ron'],'exact_50_linked':sorted(old50),
                'of_original_49_linked':sorted(first49&old50),'of_original_49_skipped':sorted(first49-old50),
                'actual_ty_server':{'logical_target':E2E,'original_ELF':result['all_50_full_elf_sha256'][E2E],'real_emitters':matches,'real_linkers':links,
                   'native_catalog_count':len(tests),'native_catalog_sha256':digest(c.raw(root+'/e2e-list.stdout.gz')),'selected_case':RUN_CASE,
                   'positive_exit':c.json(root+'/e2e-case.json')['exit'],'missing_snapshot_exit':c.json(root+'/e2e-snapshot.json')['missing_root_exit']},
                'observed_trivia_reader_text':result['native_readers']['two_trivia_consumers']}
    return {'release':role,'source':q['source'],'source_reversal':q['historical_edit'],'typed_executable_inventory':102,'typed_test_inventory':84,
            'raw_ELF_matches_out_of_250':q['exact_250_cmp'],'raw_ELF_exceptions':exceptions(c,role,q),'phases':phases}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('role',choices=['20','21']);p.add_argument('archive',type=Path);args=p.parse_args()
    registered=json.loads(gzip.decompress((HERE/('linux-release-'+args.role+'-results.json.gz')).read_bytes()))
    with args.archive.open('rb') as f:
        need(args.archive.stat().st_size==registered['archive_bytes'] and hashlib.file_digest(f,'sha256').hexdigest()==registered['archive_sha256'],'different original Linux archive')
    c=observed.Corpus(args.archive);q=observed.verify(c,args.role)
    need(q==c.json(args.role+'/independent-linux-50.json') and reconstruct(c,args.role,q)==registered['results'],'different physical Linux evidence')
    print('Original 50 destinations, 250 complete ELF comparisons and the real ty_server reader verified for release -'+args.role)
