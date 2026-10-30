"""Locate every original byte difference in the twelve unqualified Ruff bin harnesses."""
import argparse
from bisect import bisect_left
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-apple-zmij')]
import apple_reopen as workspace
from macho_paths import root_cgu
from packages import need
from reopen_response_native import signature
from study import digest

ZIP='35cf3c8f6014ac1c877307cc05bad250b160fe10691f8fa22cba2389b19130c0'
SIZE=1476457114
UNIT='crates/ruff|ruff|bin'
STAGES={'cold':'old','unchanged-old':'old','edit':'new','repeat-1':'new','repeat-2':'new','repair':'new'}


def describe(data,output,argv):
    """Authenticate all signed pages and the exact direct-object debug-string fields."""
    pages=signature(data)
    count,size=struct.unpack_from('<II',data,16);pos=32;sections={};syms=sig=None
    for _ in range(count):
        kind,sz=struct.unpack_from('<II',data,pos)
        if kind==2:syms=struct.unpack_from('<IIII',data,pos+8)
        if kind==0x1d:sig=struct.unpack_from('<II',data,pos+8)
        if kind==0x19:
            ns,=struct.unpack_from('<I',data,pos+64);need(sz==72+80*ns,'malformed Mach-O sections')
            for i in range(ns):
                at=pos+72+i*80
                section=data[at:at+16].split(b'\0',1)[0].decode();segment=data[at+16:at+32].split(b'\0',1)[0].decode()
                _,length,offset=struct.unpack_from('<QQI',data,at+32);flags,=struct.unpack_from('<I',data,at+64)
                if flags&255 in (1,12,18):continue
                name=segment+','+section;need(offset+length<=len(data) and name not in sections,'overlapping section name or extent')
                sections[name]=[offset,length,digest(memoryview(data)[offset:offset+length])]
        pos+=sz
    need(pos==32+size and sig and syms and len(sections)==15,'unexpected enrolled native executable')
    off,total=sig;cd=off+struct.unpack_from('>I',data,off+16)[0];hash_at=cd+struct.unpack_from('>I',data,cd+16)[0]
    need(hash_at+32*pages<=len(data) and off+total==len(data),'unexpected code signature table extent')
    start,count,string,sz=syms;owners=defaultdict(list)
    for i in range(count):
        idx,t,s,d,v=struct.unpack_from('<IBBHQ',data,start+16*i)
        need(idx<sz,'symbol string outside table');owners[idx].append([i,t,s,d,v])
    offsets=sorted(owners);operands=set(argv);salts={}
    for idx,rows in owners.items():
        end=data.index(0,string+idx,string+sz);path=data[string+idx:end]
        if not path.endswith(b'.rcgu.o'):continue
        name=path.decode();m=root_cgu(name,output)
        if m is None:continue
        need(name in operands and offsets[bisect_left(offsets,idx):bisect_left(offsets,end-string)]==[idx] and
             all(row[1:]==[0x66,0,1,0] for row in rows),'CGU filename lacks sole N_OSO ownership or an actual root linker operand')
        nonce=m['nonce'].encode();at=end-len(b'.rcgu.o')-len(nonce)
        need(data[at:at+7]==nonce and m['cgu'] not in salts,'duplicate or ambiguous CGU spelling')
        salts[m['cgu']]={'offset':at,'input':name,'actual_nonce':m['nonce'],'nlist_rows':rows,'unit':m['unit']}
    need(salts,'no genuine root-CGU N_OSO input')
    return {'raw':digest(data),'bytes':len(data),'pages':pages,'page_table':hash_at,'nlist_start':start,'sections':sections,'output':output,'salts':salts}


def compare(left,right):
    a,x=left;b,y=right
    need(len(a)==len(b) and x['page_table']==y['page_table'] and x['pages']==y['pages'] and
         x['sections']==y['sections'] and x['output']==y['output'] and x['salts'].keys()==y['salts'].keys(),
         'different original length, section bytes, signature layout, stable objects or output')
    first=bytearray(a);second=bytearray(b);string_pages=set();objects=[];changed_bytes=0
    for cgu,one in sorted(x['salts'].items()):
        two=y['salts'][cgu];lo=one['offset'];hi=lo+7
        need(lo==two['offset'] and one['unit']==two['unit'] and one['nlist_rows']==two['nlist_rows'] and
             one['input'].removesuffix('.'+one['actual_nonce']+'.rcgu.o')==two['input'].removesuffix('.'+two['actual_nonce']+'.rcgu.o'),
             'direct CGU differs outside the invocation salt')
        if a[lo:hi]==b[lo:hi]:continue
        n=sum(u!=v for u,v in zip(a[lo:hi],b[lo:hi]));changed_bytes+=n
        objects.append({'stable_cgu':cgu,'left':one,'right':two,'different_original_bytes':n})
        string_pages.update(range(lo//4096,(hi-1)//4096+1));first[lo:hi]=second[lo:hi]=bytes(7)
    hashes=[];sigbytes=0
    for i in range(x['pages']):
        lo=x['page_table']+i*32;hi=lo+32
        if a[lo:hi]!=b[lo:hi]:
            n=sum(u!=v for u,v in zip(a[lo:hi],b[lo:hi]));sigbytes+=n
            hashes.append({'page':i,'left':a[lo:hi].hex(),'right':b[lo:hi].hex(),'different_bytes':n})
            first[lo:hi]=second[lo:hi]=bytes(32)
    need(a!=b and len(objects)==3 and {h['page'] for h in hashes}==string_pages and first==second,
         'a native byte changed outside the three witnessed salts and derived signed-page hashes')
    return {'raw':[x['raw'],y['raw']],'bytes_per_image':len(a),'individually_verified_pages_per_image':x['pages'],
            'exact_file_backed_sections':len(x['sections']),'actual_CGUs':objects,'different_N_OSO_salt_bytes':changed_bytes,
            'signed_page_differences':hashes,'different_derived_signature_bytes':sigbytes,'all_other_original_bytes_equal':True}


def counterexamples(a,b,argv):
    """Keep a changed executable, forged symbol owner and unwitnessed operand outside the explanation."""
    data,info=a;output=info['output'];salts=next(iter(info['salts'].values()))
    def refusal(operation,why):
        try:operation()
        except RuntimeError as exc:
            need(why in str(exc),'wrong reason for corrupt-image refusal: '+str(exc));return str(exc)
        raise RuntimeError('accepted corrupt physical evidence')
    def flip(at):
        changed=bytearray(data);changed[at]^=1;page=at//4096;lo=page*4096;sig=info['page_table']+32*page
        changed[sig:sig+32]=hashlib.sha256(changed[lo:lo+4096]).digest()
        value=bytes(changed);need(signature(value)==info['pages'],'forged control did not have a valid page signature');return value
    text=info['sections']['__TEXT,__text'][0];code=flip(text)
    owner=info['nlist_start']+16*salts['nlist_rows'][0][0]+4
    return {'validly_resigned_instruction_change':refusal(lambda:compare((code,describe(code,output,argv)),b),'different original length, section bytes'),
            'validly_resigned_non_N_OSO_owner':refusal(lambda:describe(flip(owner),output,argv),'lacks sole N_OSO ownership'),
            'missing_actual_Xcode_input':refusal(lambda:describe(data,output,[p for p in argv if p!=salts['input']]),'an actual root linker operand')}


def diagnose(c,original):
    expected={(r,s,UNIT,'unresolved-native-difference') for r in ('20','21') for s in STAGES}
    need({tuple(x) for x in original['same_release_clean_failures']}==expected and len(original['same_release_clean_failures'])==12,
         'not the 12 registered exceptions')
    bodies={};origins={};comparisons={};args={};refusals={}
    def select(r,stage):
        symbol='P' if r=='20' else 'C';seq,phase=('empty-'+stage[6:],'clean') if stage.startswith('clean-') else ('visit',stage)
        base='/'.join([workspace.lib.ROOT,symbol,seq,phase]);q=c.json(base+'/verified.json')
        row,=[x for x in q['binary_roster'].values() if workspace.key(x['unit'])==UNIT];p=row['proof'];origin=p['link_origin'];h=p['raw']
        if origin not in bodies:
            link=c.json(origin+'/link.json');need(p['physical']==link and row['sha']==h,'wrong original program')
            phase=origin.split('/workspace-image-proofs/',1)[0]
            original_exec=c.packed(phase+'/exec.json.gz')
            need(digest(original_exec)==c.json(phase+'/verified.json')['streams']['native_events'],'different complete original process stream')
            event,=[x for x in json.loads(original_exec) if (x['pid'],x['seq'])==(link['pid'],link['seq'])]
            need(digest(json.dumps(event['argv'],separators=(',',':')).encode())==link['raw_argv_sha256'] and
                 event.get('xcode_response',{}).get('sha256')==link['response_sha256'],'different physical raw Xcode argv')
            e=workspace.reopen_cgu.observed_ld(c,phase,argv_sha=link['argv_sha256'],output=link['output'],pid=link['pid'])
            need(e['seq']==link['seq'] and e['path']==link['path'] and e['cdhash']==link['cdhash'] and
                 e.get('xcode_response',{}).get('sha256')==link['response_sha256'],'wrong raw signed Xcode execution')
            payload=workspace.lib.raw_image(c,h);info=describe(payload,link['output'],e['argv'])
            need(info['raw']==h and info['bytes']==row['bytes'],'different complete original Mach-O')
            bodies[origin]=payload,info;args[origin]=e['argv'];origins[origin]={**info,'signed_ld':link,'registered_refusal':p['error']}
        return origin
    for r in ('20','21'):
        for stage,state in STAGES.items():
            a=select(r,stage);b=select(r,'clean-'+state);need(a!=b,'reused reference linker')
            comparisons[r+'/'+stage]={'sources':[a,b],'genuine_independent_old_cold_pair':stage=='cold',**compare(bodies[a],bodies[b])}
            if stage=='cold':refusals[r]=counterexamples(bodies[a],bodies[b],args[a])
    return {'archive_sha256':ZIP,'archive_bytes':SIZE,'run':41110305000,'artifact':13004433435,'registered_strict_gate_passed':False,
            'original_affected_unit':UNIT,'separate_clean_new_AA_available':False,'runtime_for_this_ruff_bin_test_harness':'not executed',
            'individual_originals':origins,'same_release_own_source_comparisons':comparisons,'native_adversarial_refusals':refusals}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive',type=Path);args=parser.parse_args()
    with args.archive.open('rb') as f:
        need(args.archive.stat().st_size==SIZE and hashlib.file_digest(f,'sha256').hexdigest()==ZIP,'different native QA ZIP')
    c=workspace.lib.Corpus(args.archive)
    try:result=diagnose(c,c.json('independent-apple-workspace.json'))
    finally:c.close()
    expected=json.loads(gzip.decompress((HERE/'apple-exceptions-receipt.json.gz').read_bytes()))
    need(result==expected,'recorded native image or debug proof differs from the original artifacts')
    print('12 whole Mach-O differences independently located; both cold A/A pairs confirmed; original gate remains failed')
