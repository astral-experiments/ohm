"""Independently compare a physically signed Wild call and a never-skipping diagnostic on the same input generation."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H))
import donor
import bound_inputs
import elf_container
import prepare_reuse
b=donor.b;w=donor.w;P=donor.P;contact=donor.contact
STAGES=[('old',None),('edit',None),('warm1',None),('warm2',None),('capability',None),('corrupt',None),('replace','replace'),('earlier','earlier'),('four','four'),('malformed','malformed'),('native-repair',None),('save','mid-read'),('save-repair',None),('final',None)]
def build(env):
    src=Path(os.environ['GITHUB_WORKSPACE'])/'wild-source';files=prepare_reuse.apply(src);build=w.root/'qa-diagnostic-build';build.mkdir()
    base=dict(env,WILD_QA_ROOT=str(w.root),CARGO_HOME=str(build/'home'),CARGO_TARGET_DIR=str(build/'target'),CARGO_BUILD_BUILD_DIR=str(build/'shared'))
    online=dict(base);online.pop('CARGO_NET_OFFLINE',None)
    subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=src,env=online,check=True,timeout=900)
    command=['cargo','+ohm','-Zohm-defaults=no','rustc','--release','--locked','-p','wild-linker','--bin','wild','-j4','--','-Ctarget-feature=+crt-static']
    with(P/'source.out').open('xb')as so,(P/'source.err').open('xb')as se:ret=subprocess.run(command,cwd=src,env=base,stdout=so,stderr=se,timeout=1800)
    assert ret.returncode==0,(P/'source.err').read_text()[-3300:]
    actor=build/'target/release/wild';headers=subprocess.check_output(['readelf','-lWd',actor]);assert b'INTERP'not in headers and b'(NEEDED)'not in headers
    out=w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd';stock=build/'original';assert w.hf(out)==donor.WILD;shutil.copy2(out,stock)
    new=out.parent/'qa-static-install';shutil.copy2(actor,new);os.replace(new,out);llvm,=list((w.sdk/'lib').glob('libLLVM.so.*'))
    b.write(P/'actor.json',{'source':{x:w.hf(src/x)for x in files},'source_pin':donor.prepare_source.BASE,'actor':w.hf(actor),'stock':w.hf(stock),'stock_install':str(out),'lock':w.hf(src/'Cargo.lock'),'llvm':w.hf(llvm),'command':command})
    return stock,llvm
def control(state,stop,stock,llvm,tag,serial,hit,latch,old_ready):
    start=time.monotonic();ready=None
    while time.monotonic()-start<150:
        new=set(state.glob('ready-*'))-old_ready
        if new:ready,=new;break
        if stop.is_set():return None
        time.sleep(.01)
    assert ready is not None,'No native e2e input handoff'
    no=ready.name[6:];assert no.isdecimal()and ready.read_bytes()==b'complete\n'
    actor=state/('actor-'+no+'.tsv');view,argv=bound_inputs.receive(actor.read_text())
    # Always preserve the physically read key, including the final argv, before any response.
    wrapper={'role':view,'candidate_requested':False,'serial':serial}
    def answer(s):
        tem=state/('answer-pending-'+no);tem.write_text(s);tem.rename(state/('answer-'+no))
    try:
        if serial:
            env=(state/('local-env-'+no)).read_bytes();assert env.endswith(b'\0')
            pairs=[r.split(b'=',1)for r in env[:-1].split(b'\0')];env=dict(pairs);assert len(pairs)==len(env)
            assert not any(x in env for x in (b'LD_PRELOAD',b'LD_AUDIT'))
            cwd=Path(json.loads(view['context']['CWD'][0][0]));p=Path(argv[19]);assert Path('/proc/'+no+'/cwd').resolve()==cwd
            begin=time.monotonic_ns()
            proc=subprocess.run(argv,executable=stock,cwd=cwd,env=env,capture_output=True,timeout=80)
            assert proc.returncode==0 and not proc.stdout and not proc.stderr,(tag,proc.returncode,proc.stderr[:500])
            snapshot=elf_container.inspect(p,llvm);wrapper['stock_elapsed_ns']=time.monotonic_ns()-begin
            b.write(P/(tag+'-signed-container.json.gz'),snapshot);wrapper['stock_native_sha256']=snapshot['sha256']
        if hit and latch and view['key']==latch['key'] and view['context']['ADMISSION']==[['true',latch['image']]]:
            wrapper['candidate_requested']=True;answer('verify '+latch['output']+' '+str(latch['size'])+'\n')
        else:answer('full\n')
    except BaseException:
        answer('full\n');raise
    return wrapper

def main():
    import threading
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']
    assert shutil.disk_usage(w.root).free>45*2**30;w.guard();b.save_elf=w.hf
    registration={'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'sdk':b.SPEC['sdk_manifest'],'reference':contact.LITERALS,'never_skip':True,'original_refusal':41702972179}
    b.write(P/'registration.json',registration)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2',H.parent/'whole_count.c','-o',w.root/'whole_count'],check=True)
    env=w.install();state=w.root/'native-donor-state';state.mkdir();stock,llvm=build(env);b.select(b.OLD);b.write(P/'registry.json.gz',b.inputs(env));provider=donor.provider_file()
    meta=json.loads(subprocess.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env));assert len(meta['workspace_default_members'])==55
    result={};signed_reference=None;previous=None
    for tag,mode in STAGES:
        if tag=='edit':b.select(b.NEW);assert b.verdict(out,'withheld-old-fails',env,101)==contact.LITERALS['list']
        if tag=='corrupt':
            stat=out.stat();i=donor.text_flip(out);os.utime(out,ns=(stat.st_atime_ns,stat.st_mtime_ns));assert w.hf(out)!=contact.LITERALS['new'];b.write(P/'corrupt-preset.json',{'text_offset':i,'sha256':w.hf(out)})
        cap=os.open(out,os.O_PATH|os.O_CLOEXEC)if tag=='capability'else None
        if cap is not None:old_id=os.fstat(cap)
        failed=mode in ('malformed','mid-read');before=set(state.glob('actor-*.tsv'));ready=set(state.glob('ready-*'));stop=threading.Event()
        serial=not failed and tag not in ('capability','corrupt','replace')
        if not failed:(state/'coordinate').touch(exist_ok=False)
        if serial:(state/'stock-reference').touch(exist_ok=False)
        if mode:(state/('mid-read'if mode=='mid-read'else'entry-wait')).touch(exist_ok=False)
        with ThreadPoolExecutor(max_workers=2)as pool:
            target=pool.submit(control,state,stop,stock,llvm,tag,serial,False,None,ready)if not failed else None
            mutate=pool.submit(donor.witness,state,mode,provider,out)if mode else None
            try:
                if failed:
                    td=P/tag;td.mkdir();b.run(b.CMD,env,td,101);rows=[json.loads(x)for x in (td/'stdout.jsonl').read_bytes().splitlines()];assert rows[-1]=={'reason':'build-finished','success':False}
                    messages=(td/'stderr').read_bytes()+(td/'stdout.jsonl').read_bytes();assert (b'generation changed'if mode=='mid-read'else b'DELIBERATELY')in messages
                else:
                    inv=b.inventory(tag,env,meta);out=w.root/inv['binary'];assert len(inv['executables'])==102 and out.name==contact.BASE
            finally:stop.set()
            held=target.result()if target else None;mutation=mutate.result()if mutate else None
        a=donor.outputs(before,tag,state,out,not failed)
        if mutation:a['mutation']=mutation
        if held is not None:a['handoff']=held
        if not failed:
            assert held and not held['candidate_requested'];native=elf_container.inspect(out,llvm);b.write(P/(tag+'-source-container.json.gz'),native)
            assert native['sha256']==a['sha256'] and native['buildid']==native['zeroed_complete_buildid']
            if serial:
                s=json.loads(gzip.decompress((P/(tag+'-signed-container.json.gz')).read_bytes()))
                a['signed_relationship']=elf_container.compare(s,native)
                if s['sha256']!=native['sha256']:
                    # Both artifacts are distinct real emissions. Write their complete section
                    # and complement record before rejecting, including the signed verdict.
                    b.write(P/(tag+'-typed-difference.json'),a)
                    raise AssertionError('signed/source DIFFERED ON THE SAME LIVE LINK: '+tag)
            if tag=='edit':signed_reference=native
            if signed_reference and tag!='four':a['prior_clean_relationship']=elf_container.compare(signed_reference,native)
            if tag in ('old','edit','warm1','warm2','capability','corrupt','replace','earlier'):assert native['sha256']==contact.LITERALS['old'if tag=='old'else'new']
            if cap is not None:
                try:
                    assert (old_id.st_dev,old_id.st_ino)!=(native['dev'],native['ino'])
                    # A regular old read would deny a write lease, but O_PATH is invisible to
                    # the exclusive lease. Exercise this actual stale capability after publishing.
                    fd=os.open('/proc/self/fd/'+str(cap),os.O_WRONLY);assert os.pwrite(fd,b'\0\0',18)==2;os.close(fd)
                    assert w.hf(out)==native['sha256'];a['old_capability']=[old_id.st_dev,old_id.st_ino,old_id.st_size,os.fstat(cap).st_nlink]
                finally:os.close(cap)
            if tag=='four':
                t=subprocess.run([out,'--list'],cwd=w.work/'crates/ty_server',env=env,capture_output=True);assert t.returncode==83 and not t.stdout;a['exit']=t.returncode
            else:assert b.verdict(out,tag+'-verdict',env,0)==contact.LITERALS['list']
        b.write(P/(tag+'-complete.json'),a);result[tag]=a
        for f in ('coordinate','stock-reference','mid-read','entry-wait','entry-ready','read-first-half','entry-continue','continue-read'):(state/f).unlink(missing_ok=True)
        for f in state.glob('local-env-*'):f.unlink()
    assert not list(P.rglob('*.elf*'));b.write(P/'complete.json',result)
if __name__=='__main__':main()
