"""Read the physically authenticated native guard and span receipts. Uses the standard library and GNU tar with zstd for the physical full-role DSO."""
from pathlib import Path
import argparse
import ast
import gzip
import hashlib
import json
import re
import struct
import shutil
import subprocess
import tempfile
import zipfile

REGISTERED={
 'guard':(1628528,'371c022ccae7cf3701810606aa82b8074c9c625cb5af04c624c5688d18f8fc67'),
 'observer':(9446924,'74933fe90daeb5b2b8d0b4ec48bd9d84356a7991028cf185c0734e744b930acc'),
 'whole_role':(24326,'07ab0b1b391c8b31d24c71cdf6cb737cf9e844bbe88bc39d3ff51b59a0fa36cc'),
}
SIGNED_ALIAS='/home/runner/work/_temp/ohm-foreign-join/rustup/toolchains/ohm/bin/rustc'
EXEC=re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*\]), (?:0x[0-9a-f]+|NULL).*?\)\s*= 0$')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
get=lambda z,member:json.loads(z.read(member))


def sections(raw):
    assert raw[:6]==b'\x7fELF\x02\x01'
    off=struct.unpack_from('<Q',raw,40)[0]
    ent,n,nn=struct.unpack_from('<HHH',raw,58)
    a=[struct.unpack_from('<IIQQQQIIQQ',raw,off+i*ent) for i in range(n)]
    names=raw[a[nn][4]:a[nn][4]+a[nn][5]]
    return {names[k:names.index(0,k)].decode():sha(raw[p:p+size]) for k,t,_,_,p,size,*_ in a if t!=8}


def native_bytes(good,d):
    bad=bytearray(good)
    assert len(good)==d['size'] and sha(good)==d['normal']
    for off in d['offsets']:
        assert good[off:off+24]==b'serialize_newtype_struct'
        bad[off+23]=ord('x')
    assert sha(bad)==d['malformed']
    old,new=sections(good),sections(bad)
    assert {k for k in old if old[k]!=new[k]}=={'.rodata'}


def guard(z):
    sdk=get(z,'sdk-proof.json')
    assert sdk['files']==79 and 'd57fd151' in sdk['rustc'] and '7024b0d2' in sdk['cargo']
    d=get(z,'actual-dso.json');native_bytes(gzip.decompress(z.read('original-serde.so.gz')),d)
    rows={}
    for tag in get(z,'result.json')['rows']:
        msgs=[json.loads(l)for l in z.read(tag+'/stdout.jsonl').splitlines()]
        ok=msgs[-1]['success'];assert msgs[-1]['reason']=='build-finished'
        ips=[]
        for name in z.namelist():
            if not name.startswith(tag+'/exec.'):continue
            for ln in z.read(name).decode().splitlines():
                result=EXEC.fullmatch(ln)
                if result and ast.literal_eval(result[1])==SIGNED_ALIAS:
                    argv=ast.literal_eval(result[2])
                    if argv[0]==SIGNED_ALIAS and '--crate-name'in argv and argv[argv.index('--crate-name')+1]=='ron':ips.append(name)
        stale=tag.startswith('ablated-')
        assert len(ips)==(0 if stale else 1)
        errors=[]
        for m in msgs:
            if m['reason']!='compiler-message' or m['message']['level']!='error':continue
            e=m['message']
            for s in e['spans']:
                if s['is_primary']:errors.append([e['code']['code'],Path(s['file_name']).name,s['line_start'],s['column_start'],s['line_end'],s['column_end']])
        if ok:
            assert b'Extensions("IMPLICIT_SOME")' in z.read(tag+'/native') and b'1 passed;' in z.read(tag+'/native')
            assert z.read(tag+'/test-list').splitlines()==[b'tests::current_ron_extension: test']
        rows[tag]={'ron_execs':len(ips),'build_ok':ok,'errors':errors}
    assert rows['ablated-first']['build_ok']and rows['ablated-again']['build_ok']
    assert rows['ordinary-malformed']['errors']==rows['empty-same-malformed']['errors']
    assert not rows['ordinary-malformed']['build_ok']and not rows['real-source-malformed']['build_ok']
    assert get(z,'result.json')['rows']['repair']['elf']==get(z,'result.json')['rows']['empty-repair']['elf']
    return {'dso':d,'stages':rows}


def observer(z):
    h=json.loads(gzip.decompress(z.read('signed-ron-replay/native-hits.json.gz')))
    orig=get(z,'original-comparison.json')
    prod=get(z,'signed-ron-replay/actual.json')
    assert h['exit_codes']==[0]and h['events']=={'join':3} and h['entry_counts']=={'span_join':68}
    assert len(h['actual_returns'])==len(h['join_sources'])==3
    for r,j in zip(h['actual_returns'],h['join_sources']):
        assert r['some_tag']==1 and r['first']!=r['returned']
        assert [j['first']['relative_lo'],j['first']['len'],j['second']['relative_lo'],j['second']['len']]==[549,1,602,8]
    inputs={r[k]for r in h['actual_returns']for k in ('first','second')}
    returns={r['returned']for r in h['actual_returns']}
    assert len(returns)==1 and not inputs&returns
    assert len(h['detailed_matches'])==2 and all(t=='span_join' and all(s in inputs for _,s in a)for t,a,_,_ in h['detailed_matches'])
    assert prod['rlib_original']==prod['rlib_replayed']and prod['depinfo_identical_under_output_relocation']
    names=re.compile(r'/v2-[0-9a-f]{16}/')
    assert [names.sub('/v2/',x)for x in orig['prior_full_argv']]==[names.sub('/v2/',x)for x in orig['current_full_argv']]
    return {'bridge_entries':h['entry_counts'],'foreign_stores':h['events'],'returned_range':[549,610],'rmeta_equal_within_replay':prod['rmeta_original']==prod['rmeta_replayed'],'rlib':prod['rlib_original'],'locations':get(z,'source-witness.json'),'argv_layout_differences':len(orig['argv_differences'])}


def whole(z):
    hist=get(z,'histories.json');out={}
    for tag,row in hist.items():
        raw=[json.loads(l)for l in z.read(tag+'/stderr').splitlines()if l.startswith(b'{')]
        errors=[]
        for m in raw:
            if m.get('level')!='error' or not m.get('code'):continue
            for s in m['spans']:
                if s['is_primary']:errors.append([m['code']['code'],Path(s['file_name']).name,s['line_start'],s['column_start'],s['line_end'],s['column_end']])
        if tag.startswith(('inspect-','clamp-')):
            b=get(z,tag+'/returns.json')
            assert b['exit_codes']==[1]and len(b['returns'])==3 and not b['pending']
            assert all(r['returned']==r['first' if tag.startswith('clamp-')else 'original'] for r in b['returns'])
        out[tag]={'errors':errors,'products':row['products'],'returns':len(row.get('bridge',{}).get('returns',[]))}
    before=out['signed-healthy']['products'];restored=out['signed-repair']['products']
    assert set(before)==set(restored)
    assert [p for p in before if before[p]!=restored[p]]==['libron-0b42003ff6bbcee9.rmeta']
    assert before['libron-0b42003ff6bbcee9.rlib']=='da159c2ae58df1a78438e7afb316ae9e4659ce0a9fabccba7e83a3a1de8b70b3'
    normal=out['signed-malformed']['errors'];changed=out['clamp-return-malformed']['errors']
    assert normal==out['inspect-malformed']['errors']
    assert sorted(normal)==sorted([['E0782','extensions.rs',5,83,5,94],['E0782','public.rs',17,37,17,98]])
    assert sorted(changed)==sorted([['E0782','extensions.rs',5,83,5,94],['E0782','public.rs',17,37,17,38]])
    return {'malformed':get(z,'full-malformed-so.json'),'stages':out}


def main():
    ap=argparse.ArgumentParser()
    for k in REGISTERED:ap.add_argument(k,type=Path)
    args=ap.parse_args();data={}
    for k,read in [('guard',guard),('observer',observer),('whole_role',whole)]:
        path=getattr(args,k)
        with path.open('rb')as f:
            assert (path.stat().st_size,hashlib.file_digest(f,'sha256').hexdigest())==REGISTERED[k]
        with zipfile.ZipFile(path)as z:
            assert len(z.namelist())==len(set(z.namelist()));data[k]=read(z)
    desc=data['whole_role']['malformed']
    assert desc['normal']=='406b8448ec89af1429a3a253381c6d9176970deb874c1035e680264ba8df382b'
    with zipfile.ZipFile(args.observer)as z,tempfile.NamedTemporaryFile()as tar:
        with z.open('role-files.tar.zst')as src:shutil.copyfileobj(src,tar)
        tar.flush()
        plain=subprocess.check_output(['tar','--zstd','-xOf',tar.name,'./'+desc['normal']])
        native_bytes(plain,desc)
    print(json.dumps(data,sort_keys=True,indent=2))


if __name__=='__main__':main()
