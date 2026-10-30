"""Independently time real Ruff typeshed test builds after a traced two-order admission."""
import argparse
import ctypes
import gzip
import itertools
import json
import os
from pathlib import Path
import shutil
import zipfile

from cohort import fingerprint_sources, summarize
from execs import ExecTrace
from macho_paths import compare
from measure import capture, fresh, retire, select
from native_inputs import run_archive_check
from study import CHILD, MISSING, PARENT, RECHECK, check_host, compress_bytes, digest, env_for, load, need, save, sdk_id, sha
from ty_disk import snapshot
from zlib_study import CMD, NEW, OLD, checkout, installation, product

ENDPOINTS=("edit","repeat-1","repeat-2")
ALLOCATION=int(digest(("crc typeshed on exact 735e1528, inclusive complete-compile 12 v2 / "+PARENT+CHILD+OLD+NEW).encode()),16)%924
FIRST=set(list(itertools.combinations(range(12),6))[ALLOCATION])
ORDERS={"screen":["PC","CP"],"confirmation":["PC" if i in FIRST else "CP" for i in range(12)]}


def enroll(path, expected):
    need(len(expected)==64 and sha(path)==expected, "different structural archive")
    with zipfile.ZipFile(path) as z:
        need(z.testzip() is None and len(z.namelist())==len(set(z.namelist())), "damaged structural archive")
        def data(n):return json.loads(z.read(n))
        pair=data("pair.json")
        need([pair["products"][r]["source"] for r in "PC"]==[PARENT,CHILD], "different native compilers")
        for order in ("PC","CP"):
            need(data("crc-comparison/"+order+"/verdict.json")["structural_screen"],"unqualified structural mirror")
            for role in order:
                top="crc-comparison/"+order+"/"+role+"/"
                clean={v:data(top+"clean-"+k+"/clean/verified.json")["product"] for v,k in ((OLD,"old"),(NEW,"new"))}
                for phase in ("edit", "repeat-1","repeat-2","invalid","repair"):
                    d=top+"visits/"+phase+"/"; v=data(d+"verified.json")
                    native=gzip.decompress(z.read(d+"exec.json.gz")); stdout=gzip.decompress(z.read(d+"stdout.gz"))
                    need(digest(native)==v["streams"]["streams"]["native_events"] and digest(stdout)==v["streams"]["streams"]["stdout"],"altered native streams")
                    events=json.loads(native);msgs=list(map(json.loads,stdout.splitlines()))
                    rustcs=[e["argv"][e["argv"].index("--crate-name")+1] for e in events if e["path"].endswith("/native/bin/rustc") and "--crate-name" in e["argv"]]
                    lds=[e["argv"] for e in events if e["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld")]
                    rr=[args for args in lds if [b for a,b in zip(args,args[1:]) if a=="-o"]==[v["output"]]]
                    need(v["code"]==(101 if phase=="invalid" else 0) and msgs[-1]=={"reason":"build-finished","success":phase!="invalid"},"missing actual Cargo verdict")
                    if phase.startswith("repeat"):
                        need(len(rr)==int(role=="P") and (rustcs.count("zlib_rs")>0)==(role=="P"),"zlib compile and direct native link not removed")
                    if phase in ("edit","repair"):
                        need(len(rr)==1 and "ty_vendored" in rustcs, "real edit or repair did not relink")
                    if phase!="invalid":
                        need(clean[v["rev"]]==v["product"] and v["product"]["tests"],"whole product changed")
                    else:
                        need(not rr and b"E0425" in stdout,"invalid source accepted")
                for st in ("old","new"):
                    ref=clean[OLD if st=="old" else NEW]
                    need(digest(gzip.decompress(z.read("crc-programs/"+ref["raw"]+".gz")))==ref["raw"],"missing clean program")
        for role in "PC":
            h=data("native-input/"+role+"/terminal.json")
            need([h[k]["value"] for k in ("initial","unchanged","replace","repair","empty-reference")]==[17,17,29,29,29],"native value drift")
            need(h["malformed"]["cargo_exit"]==h["missing"]["cargo_exit"]==101 and h["repair"]["executable"]==h["empty-reference"]["executable"],"bad declared native input or repair accepted")
    return {"sha256":expected,"rust":[PARENT,CHILD],"ruff":[OLD,NEW],"prior":"two traced orders, independently clean old and new, invalid/repair/declared archive"}


def typed(stream):
    msgs=list(map(json.loads,stream.splitlines()))
    need(msgs[-1]=={"reason":"build-finished","success":True},"unfinished Cargo command")
    arts=[r for r in msgs if r["reason"]=="compiler-artifact"]
    sig=sorted(json.dumps([u[k] for k in ("package_id","target","features","profile")],sort_keys=True,separators=(",",":")) for u in arts)
    return msgs,arts,{"roster":digest(json.dumps(sig).encode()),"dirty":sorted(u["target"]["name"] for u in arts if not u["fresh"])}


def clone(src, dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    fn=ctypes.CDLL(None,use_errno=True).clonefile
    fn.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint32]
    need(fn(os.fsencode(src),os.fsencode(dst),0)==0,"APFS result clone failed")


def typed_zlib(arts):
    return [x for x in arts if x["target"]["name"]=="zlib_rs" and x["target"]["kind"]==["lib"]]


def depfiles(work, arts):
    result={}
    for u in typed_zlib(arts):
        lib,=[Path(f) for f in u["filenames"] if f.endswith(".rlib")]
        name=lib.stem.removeprefix("lib")+".d"
        candidates={ (p.stat().st_dev,p.stat().st_ino):p for folder in ("target","shared") for p in (work/folder).rglob(name)}
        dep,=candidates.values()
        result[str(lib)]=dep
    need(result,"no registry dep-info")
    return result


def anchored(root,role,phase):
    start=root/"receipts/crc-clock-before/PC"/role
    code=load(start/("clean-old" if phase=="cold" else "clean-new")/"clean/verified.json")
    with gzip.open(start/"visits"/phase/"stdout.gz","rb") as f:
        _,_,sig=typed(f.read())
    return code,sig


def timed(root, out, role):
    work=root/"crc-work";repo=root/"ruff";sdk=select(root,role);env=env_for(work,sdk)
    check_host(root,8);fresh(work,root/"seed"); before=sdk_id(sdk,env)
    saved=work/"clock-hold";need(not saved.exists(),"stale timed program")
    pending=[]
    deps=None
    for phase in ("cold",*ENDPOINTS):
        rev=OLD if phase=="cold" else NEW
        if phase in ("cold","edit"):checkout(repo,rev)
        cap=out/phase
        code,stdout,stderr,events,clock=capture(CMD,repo,env,cap,clock=phase!="cold")
        need(events is None and code==0,f"Cargo failed: {stderr[-450:]!r}")
        msgs,arts,sig=typed(stdout)
        exe,=[Path(r["executable"]) for r in arts if r["executable"] and r["target"]["name"]=="ty_vendored" and r["profile"]["test"]]
        build,=[r for r in msgs if r["reason"]=="build-script-executed" and "/ty_vendored#" in r["package_id"]]
        held=(saved/phase/"program",saved/phase/"typeshed.zip")
        clone(exe,held[0]);clone(Path(build["out_dir"])/"zipped_typeshed.zip",held[1])
        if deps is None:deps=depfiles(work,arts)
        members=[v for z in typed_zlib(arts) for v in z["filenames"] if v.endswith(".rlib")]
        need(set(members)==set(deps),"zlib outputs changed")
        markers=[deps[v].read_bytes() for v in members]
        pending.append((phase,rev,cap,msgs,arts,sig,clock,held,markers))
    rows={}
    for phase,rev,cap,msgs,arts,sig,clock,held,markers in pending:
        ref,wanted=anchored(root,role,phase)
        _,p=product(root,repo,rev,cap,arts,msgs,held)
        need(p==ref["product"] and sig==wanted,"timed product or actual typed work differs from the separately clean and traced references")
        mz=[]
        for i,raw in enumerate(markers):
            need(b"zlib-rs-0.5.5/src/" in raw and (MISSING in raw)==(role=="P") and (role=="P" or RECHECK in raw),"registry mechanism changed")
            mz.append(compress_bytes(cap/f"zlib-{i}.dep.gz",raw))
        row={"cargo":clock,"product":p,"zlib_dep_sha":mz,"signature":sig,"phase":phase}
        save(cap/"result.json",row);rows[phase]=row
    shutil.rmtree(saved)
    disk=snapshot(work,out/"steady-disk")
    need(before==sdk_id(sdk,env),"wrong compiler after the last clock")
    retire(work)
    print(role,out.parent.name,rows["repeat-1"]["cargo"]["ns"],disk["all"]["allocated_bytes"],flush=True)
    return rows


def initial(root):
    from receipt_cargo import CANDIDATE
    native=load(root/'receipts/provider-matrix/terminal.json')
    need(native['passed'] and native['commands']==392, 'CRC provider safety rejected the stack')
    out=root/'receipts/crc-clock-before'; trace=ExecTrace();trace.ready();eligible=True
    try:
        for order in ('PC','CP'):
            refs={};baseline={}
            for role in order:
                check_host(root,8)
                refs[role],baseline[role]=installation(root,role,out/order/role,trace)
            per={}
            for step in ENDPOINTS:
                phases={}
                for r in 'PC':
                    row=baseline[r][step];n=row['native'];cert=load(out/order/r/'visits'/step/'native-link-receipt.json')
                    seals=[x['records'] for x in cert['aliases'].values() if {'seal','product'}<=x['records'].keys()]
                    protected=any(x['product']['sha256']==row['product']['raw'] for x in seals)
                    linked_outputs=[Path(b).name for linker in n['linkers'] for a,b in zip(linker['argv'],linker['argv'][1:]) if a=='-o']
                    p={'zlib_full':n['full'].count('zlib_rs'),'full':n['full'],'link_only':n['link_only'],'ld':len(n['linkers']),
                       'build_script_ld':linked_outputs.count('build_script_build'),
                       'root_ld':len(row['root_link_argv']),'driver':len(n['cargo_link_driver']),'sealed_output':protected,
                       'hard':[x['hard'] for x in row['zlib']],'recheck':[x['recheck'] for x in row['zlib']]}
                    phases[r]=p
                p,c=phases['P'],phases['C']
                retained=['build_script_build','ty_vendored']
                passed=(c['full']==retained and p['full']==retained+['zlib_rs','zlib_rs']
                        and len(p['hard'])==len(c['hard'])==2 and all(p['hard']) and not any(c['hard']) and all(c['recheck'])
                        and all(not role['link_only'] and role['ld']==2 and role['root_ld']==role['build_script_ld']==1
                                and role['driver']==1 and role['sealed_output'] for role in (p,c)))
                eligible=eligible and passed;per[step]={'passed':passed,'roles':phases}
            for rev in (OLD,NEW):
                arms={}
                for role in 'PC':
                    row=refs[role][rev];image=gzip.decompress((root/'receipts/crc-programs'/(row['product']['raw']+'.gz')).read_bytes())
                    arms[role]=image,row['output'],row['root_link_argv'][0]
                save(out/order/(rev+'-cross.json'),compare(arms))
            save(out/order/'verdict.json',per)
        for role in 'PC':run_archive_check(root,role,trace)
    finally:trace.close()
    gate={'cargo':CANDIDATE,'rust':[PARENT,CHILD],'ruff':[OLD,NEW],'structural':eligible,'provider':sha(root/'receipts/provider-matrix/terminal.json'),'harness':fingerprint_sources()}
    save(root/'receipts/declared-crc-subject.json',gate);print('structural',eligible,flush=True)


def stage(root, mode):
    gate=load(root/"receipts/declared-crc-subject.json")
    out=root/"receipts"/("crc-clock-"+mode)
    harness=fingerprint_sources()
    if mode=="confirmation":
        before=load(root/"receipts/crc-clock-screen/result.json")
        need(before["valid"] and before["harness"]==harness,"no valid independent pilots")
    save(out/"registered.json",dict(eligible=gate,order=ORDERS[mode],assignment=ALLOCATION,harness=harness,argv=CMD,
                                     primary="first unchanged test build after historical typeshed revision",
                                     secondary=["edit","second unchanged test build"],independent_clean="complete native Mach-O, embedded ZIP and both real tests on every visit"))
    need(gate["structural"] and gate["harness"]==harness, "structural native gate rejected")
    pairs=[]
    for i,order in enumerate(ORDERS[mode],1):
        pairs.append({r:timed(root,out/f"pair-{i:02}"/r,r) for r in order})
    clocks=summarize(pairs,ORDERS[mode]);first=clocks["repeat-1"]
    passed=(min(first["ratios_P_over_C"])>2 if mode=="screen" else first["median_CI_96.14pct"][0]>2 and first["one_sided_balanced_sharp_2x_p"]<=.05)
    if mode=="confirmation":
        from zlib_study import phase as observed
        trace=ExecTrace()
        try:
            trace.ready();work=root/"crc-work"
            for role in "CP":
                sdk=select(root,role);env=env_for(work,sdk);fresh(work,root/"seed");checkout(root/"ruff",NEW)
                end=observed(root,work,sdk,env,out/"terminal-clean"/role,"clean",NEW,trace)
                need(end["product"]==anchored(root,role,"edit")[0]["product"],"independent terminal clean executable drift")
                retire(work)
        finally:
            trace.close()
    save(out/"result.json",dict(passed=passed,valid=True,harness=harness,order=ORDERS[mode],wall=clocks))
    print(mode,first,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("enroll","structural","screen","confirmation"))
    parser.add_argument("root",type=Path)
    parser.add_argument("--sha256")
    a=parser.parse_args();root=a.root.resolve(strict=True)
    if a.mode=="enroll":save(root/"receipts/declared-crc-subject.json",enroll(root/"prior-typeshed.zip",a.sha256))
    elif a.mode=="structural":initial(root)
    else:stage(root,a.mode)
