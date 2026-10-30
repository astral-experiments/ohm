"""Pin one native Cargo #293 for both Rust roles and qualify real CRC native provider transitions."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from dyld import check as check_dyld
from execs import ExecTrace
from measure import select
from prepare import role_files
import provider_edges as edge
from receipt_cargo import CANDIDATE
from study import PARENT, CHILD, check_host, env_for, load, need, physical, save, sdk_id, sha

INPLACE=(("original-higher","higher",7),("repeat-higher","higher",7),("overwrite-same-stamp","overwrite",7),
         ("repeat-replacement","overwrite",7),("restore-same-stamp","restore",7))

def evidence(work,dest,row):
    records={}
    for dirname in ("target","shared"):
        for alias in sorted((work/dirname).rglob("ohm-link-cc")):
            if not alias.is_symlink():continue
            objects=alias.parent
            cache=objects/"native-link"
            files={}
            for name in ("lock","seal","product"):
                f=cache/name
                if f.is_file() and not f.is_symlink():
                    st=f.stat()
                    files[name]={"size":st.st_size,"sha256":sha(f),"inode":st.st_ino}
                    if name=="seal":
                        need(st.st_size<=65568,"oversized seal");files[name]["hex"]=f.read_bytes().hex()
            records[str(alias.relative_to(work))]={"target":os.readlink(alias),"records":files}
    events=json.loads(gzip.decompress((dest/"exec.json.gz").read_bytes()))
    driver=row["native"]["cargo_link_driver"]
    dry=[e["pid"] for e in events if "-###" in e["argv"]]
    rec=[x for x in row["native"]["linkers"] if "-dependency_info" in x["argv"]]
    save(dest/"native-link-receipt.json",{"aliases":records,"driver_processes":driver,"clang_dry_run_pids":dry,
         "ld_dependency_info":len(rec),"full":row["native"]["full"],"link_only":row["native"]["link_only"],
         "stock_links":len(row["native"]["linkers"])})


def same_stamp(src,state,bodies):
    if state=="higher":return edge.configure(src,state,bodies)
    path=src/"early/libqa_owned_external.a"
    want=bodies[17 if state=="overwrite" else 29];old=path.read_bytes();st=path.stat()
    need(len(old)==len(want) and state in {"overwrite","restore"},"unexpected archive size or state")
    if old!=want:
        with path.open("r+b") as f:f.write(want);f.flush();os.fsync(f.fileno())
        os.utime(path, ns=(st.st_atime_ns,st.st_mtime_ns))
    now=path.stat()
    need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)
         and path.read_bytes()==want,"unstable in-place witness")
    return {"early":sha(path),"late":sha(src/"late/libqa_owned_external.a"),"modification":old!=want,
            "prior_sha256":edge.digest(old),"device":st.st_dev,"inode":st.st_ino,"size":st.st_size,
            "mtime_ns":st.st_mtime_ns,"before_ctime_ns":st.st_ctime_ns,"after_ctime_ns":now.st_ctime_ns}

def pin(root):
    product=load(root/'receipts/cargo293/product.json')
    need(product['source']['commit']==CANDIDATE and product['binary']['sha256']==sha(root/'cargo-293'), 'unbound #293 build')
    pair=load(root/'receipts/pair.json');need([pair['products'][r]['source'] for r in 'PC']==[PARENT,CHILD] and len(pair['differ'])==1,'uncertified compiler pair')
    # The library directory swap preserves both Rust driver stamps; the Cargo executable never moves again.
    sdk=select(root,'P');dst=sdk/'bin/cargo';signed=load(root/'receipts/release.json')
    need(dst.samefile(root/'signed/bin/cargo') and sha(dst)==signed['cargo']['sha256'],'missing signed initial reference')
    next_path=dst.with_name('cargo-293.next');os.link(root/'cargo-293',next_path);os.replace(next_path,dst)
    cert={'commit':CANDIDATE,'binary':physical(dst),'build_receipt':sha(root/'receipts/cargo293/product.json'),'signed_reference':signed['cargo']['sha256']}
    save(root/'receipts/fixed-cargo-293.json',cert)
    rg={}
    for role in 'PC':
        sdk=select(root,role);env=env_for(root/'crc-pin',sdk);identity=sdk_id(sdk,env)
        members=role_files(sdk);prior=pair['products'][role]['runtime'];expected={**prior,'bin/cargo':cert['binary']['sha256']}
        need(members==expected and identity['cargo']==cert['binary'],'SDK changed outside the enrolled Cargo and driver')
        check_dyld(root,role,sdk,root/'receipts/293-runtime'/role/'dyld')
        rg[role]={'sdk':identity,'members':members,'cargo_ctime_ns':dst.stat().st_ctime_ns}
    need(rg['P']['cargo_ctime_ns']==rg['C']['cargo_ctime_ns'] and rg['P']['sdk']['std']==rg['C']['sdk']['std'],'unmatched studies')
    save(root/'receipts/293-runtime/pair.json',rg)


def providers(root):
    matrix=root/'receipts/provider-matrix';matrix.mkdir();
    for n in ('edge-images','edge-markers'):(root/'receipts'/n).mkdir()
    need('crc32w {v:w}, {v:w}, {d:w}' in edge.BARRIER and edge.BARRIER.count('asm!')==1,'wrong assembly source')
    order=[(p,w,default,r) for p in ('direct','library') for w in ('unwatched','declared') for default in (True,False) for r in 'PC']
    save(matrix/'registration.json',{'cargo':CANDIDATE,'rust':{'P':PARENT,'C':CHILD},'cases':order,'steps':edge.STEPS,'inplace':INPLACE,'barrier':edge.BARRIER,'fixture':sha(Path(edge.__file__))})
    bodies=edge.provider_factory(root,matrix);trace=ExecTrace();trace.ready();checks={};off=[]
    try:
        for p,w,default,r in order:
            label='-'.join((r,p,w,'default' if default else 'off'))
            rows=edge.run_case(root,trace,r,p,w,default,bodies,evidence=evidence)
            checks[label]=[]
            for name,state,rust in edge.STEPS:
                v=rows[name];value=edge.NATIVE[state];expected=[0,[value,rust]] if value is not None else [101,None]
                need(v['empty'][:2]==expected,'wrong independently empty native reference')
                if default or w=='declared' or name not in edge.NO_RUST:
                    if v['warm'][:2]!=expected or v['same_raw'] is False:checks[label].append(name)
                elif v['warm'][:2]!=expected:off.append([label,name,v['warm'][:2],expected])
            print('closed',label,checks[label],flush=True)
        for r in 'PC':
            for p in ('direct','library'):
                label=f'{r}stamp-{p}-unwatched-default';checks[label]=[]
                rows=edge.run_case(root,trace,r,p,'unwatched',True,bodies,visits=INPLACE,change=same_stamp,evidence=evidence,label=r+'stamp')
                for name,state,rust in INPLACE:
                    v=rows[name];expected=[0,[17 if state=='overwrite' else 29,rust]]
                    need(v['empty'][:2]==expected,'wrong empty in-place reference')
                    if v['warm'][:2]!=expected or v['same_raw'] is not True:checks[label].append(name)
    finally:trace.close()
    passed=not any(checks.values());save(matrix/'terminal.json',{'passed':passed,'wrong_or_raw_mismatch':checks,'off_unwatched_comparisons':off,'commands':352+40})
    print('native provider gate',passed,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('pin','providers'));p.add_argument('root',type=Path);a=p.parse_args()
    root=a.root.resolve();check_host(root,8);(pin if a.mode=='pin' else providers)(root)
