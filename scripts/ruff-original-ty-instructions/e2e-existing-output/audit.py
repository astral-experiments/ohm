"""Independently compare a physically signed Wild call and a never-skipping diagnostic on the same input generation."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import fcntl
import signal
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat as statmod
import subprocess
import sys
import time
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H))
import donor
import bound_inputs
import elf_container
import measure
import eligibility
import lease_cases
import symbols_control
import matched_stock
import witness
import prepare_reuse
b=donor.b;w=donor.w;P=donor.P;contact=donor.contact
STAGES=[('old',None),('edit',None),('warm1',None),('warm2',None),('capability',None),('corrupt',None),('replace','replace'),('earlier','earlier'),('four','four'),('malformed','malformed'),('native-repair',None),('save','mid-read'),('save-repair',None),('final',None)]
def build(env):
    src=Path(os.environ['GITHUB_WORKSPACE'])/'wild-source';files=prepare_reuse.apply(src)
    stage=json.loads((H/'source-preflight.json').read_bytes());assert stage['pin']==donor.prepare_source.BASE and stage['after']=={x:w.hf(src/x)for x in files}
    build=w.root/'qa-diagnostic-build';build.mkdir()
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
    # The actual default root has other real links. Their image, argv, cwd,
    # stdio and GNU jobserver descriptors must continue into signed Wild.
    literal=[str(out),'--version'];stock_control=subprocess.run(literal,executable=str(stock),env=env,capture_output=True,check=True)
    trace=P/'non-target-exec.txt';r=subprocess.run(['strace','-qq','-f','-s','8192','-e','trace=execve','-o',trace,*literal],env=env,capture_output=True,check=True)
    assert (r.stdout,r.stderr)==(stock_control.stdout,stock_control.stderr) and b'wild' in (r.stdout+r.stderr).lower()
    commands=trace.read_text();assert ('execve("'+str(out)+'"') in commands and ('execve("'+str(stock)+'", ["'+str(out)+'", "--version"]') in commands
    b.write(P/'non-target-exec.json',{'distributor_sha256':w.hf(stock),'candidate_sha256':w.hf(out),'unmodified_argv0':literal[0],'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest()})
    return stock,llvm
def control(state,stop,stock,llvm,tag,serial,hit,latch,old_ready):
    meter=measure.start();start=time.monotonic();ready=None
    while time.monotonic()-start<1200:
        new=set(state.glob('ready-*'))-old_ready
        if new:ready,=new;break
        if stop.is_set():return None
        time.sleep(.01)
    assert ready is not None,'No native e2e input handoff'
    no=ready.name[6:];assert no.isdecimal()and ready.read_bytes()==b'complete\n'
    actor=state/('actor-'+no+'.tsv');view,argv=bound_inputs.receive(actor.read_text())
    if tag=='old':b.write(P/'actual-symbols-shape-controls.json',symbols_control.run(w.root,Path(argv[36])))
    # Always preserve the physically read key, including the final argv, before any response.
    wrapper={'role':view,'candidate_requested':False,'candidate_enabled':hit,'latch_key':latch['key']if latch else None,'serial':serial,'grammar':eligibility.native_args(argv)}
    def answer(s):
        tem=state/('answer-pending-'+no);tem.write_text(s);tem.rename(state/('answer-'+no))
    try:
        if serial:
            env=(state/('local-env-'+no)).read_bytes();assert env.endswith(b'\0')
            pairs=[r.split(b'=',1)for r in env[:-1].split(b'\0')];env=dict(pairs);assert len(pairs)==len(env)
            assert not any(x in env for x in (b'LD_PRELOAD',b'LD_AUDIT'))
            cwd=Path(json.loads(view['context']['CWD'][0][0]));p=Path(argv[19]);assert Path('/proc/'+no+'/cwd').resolve()==cwd
            reference=[]
            for n in range(2 if tag in ('native-repair','save-repair') else 1):
                matched=matched_stock.run(state,H/'group_exec.py',tag,n,int(no),int(view['context']['TYPED'][0][4]),argv,stock,cwd,env)
                elapsed=matched['elapsed_ns']
                snapshot=elf_container.inspect(p,llvm)
                b.write(P/(tag+'-signed-'+str(n)+'-container.json.gz'),snapshot)
                reference.append({'elapsed_ns':elapsed,'sha256':snapshot['sha256'],'ino':snapshot['ino'],'matched_jobserver':matched})
            b.write(P/(tag+'-signed-container.json.gz'),snapshot)
            wrapper['signed_repetitions']=reference;wrapper['stock_native_sha256']=snapshot['sha256']
        if hit and wrapper['grammar'] and latch and view['key']==latch['key'] and view['context']['ADMISSION']==[['true',latch['image']]]:
            wrapper['candidate_requested']=True;answer('verify '+latch['output']+' '+str(latch['size'])+'\n')
        else:answer('full\n')
    except BaseException:
        answer('full\n');raise
    wrapper['coordinator_clock']=measure.end(meter)
    return wrapper

def calibrate(env,state):
    # The same static actor must really wait for an external full-only reply. Keep this
    # tiny actual ELF separate from the expensive cold workspace and its collector.
    tiny=w.root/'boundary-smoke';t=tiny/'ty_server/f5c6198f896cf7b0/out';t.mkdir(parents=True)
    name=t/contact.BASE;asm=tiny/'start.s';obj=tiny/'start.o'
    asm.write_text('.global _start\n.text\n_start: mov $60,%eax\n xor %edi,%edi\n syscall\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['/usr/bin/as','--64','-o',obj,asm],check=True)
    real=w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
    previous=set(state.glob('ready-*'));(state/'coordinate').touch()
    proc=subprocess.Popen([real,'--build-id','-o',name,obj],cwd=tiny,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline and not(set(state.glob('ready-*'))-previous):
        if proc.poll() is not None:break
        time.sleep(.01)
    ready,=set(state.glob('ready-*'))-previous;pid=ready.name[6:]
    p=state/('answer-'+pid);tmp=p.with_suffix('.pending');tmp.write_text('full\n');tmp.rename(p)
    so,se=proc.communicate(timeout=30);assert proc.returncode==0 and not so and not se,(proc.returncode,so,se)
    assert subprocess.run([name],timeout=5).returncode==0
    raw=(state/('actor-'+pid+'.tsv')).read_bytes();assert b'MISS\tcoordinator-full\n'in raw and b'VERIFIED\n'in raw
    (P/'calibration.tsv.gz').write_bytes(gzip.compress(raw,mtime=0));(state/'coordinate').unlink()

def stored_generations(path,native):
    names=[]
    for root in (w.target,w.shared):
        assert root.parent==w.root and root.is_dir() and not root.is_symlink()
        for base,dirs,files in os.walk(root,followlinks=False):
            for name in files:
                item=Path(base)/name
                try:info=item.lstat()
                except FileNotFoundError:continue
                if info.st_size!=native['size'] or not statmod.S_ISREG(info.st_mode):continue
                if w.hf(item)==native['sha256']:names.append(str(item))
    assert names==[str(path)],(path,names)
    return names

def main(enable=False):
    import threading
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']
    assert shutil.disk_usage(w.root).free>45*2**30;w.guard();b.save_elf=w.hf
    registration={'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'sdk':b.SPEC['sdk_manifest'],'reference':contact.LITERALS,'never_skip':not enable,'original_refusal':41702972179,'qualified_separate_source_and_elf_receiver':True}
    b.write(P/'registration.json',registration)
    measure.prepare(w.root,H.parent/'whole_count.c');b.write(P/'coordinator-calibration.json',measure.calibrate())
    env=w.install();state=w.root/'native-donor-state';state.mkdir();stock,llvm=build(env);symbols_control.build(w.root,H,env);calibrate(env,state);b.select(b.OLD);b.write(P/'registry.json.gz',b.inputs(env));provider=donor.provider_file()
    meta=json.loads(subprocess.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env));assert len(meta['workspace_default_members'])==55
    result={};signed_reference=None;latch=None
    phases=STAGES.copy()
    if enable:phases[5:5]=[('warm-control',None),('warm-repeat',None),('mid-output','mid-output'),('rename-output','rename-output'),('exclusive-collision','exclusive-collision')]
    for tag,mode in phases:
        if tag=='edit':b.select(b.NEW);assert b.verdict(out,'withheld-old-fails',env,101)==contact.LITERALS['list']
        if tag=='corrupt':
            b.write(P/'corrupt-preset.json',witness.corrupt_text(out,donor.text_flip,contact.LITERALS['new']))
        cap=lease_cases.held(out,lambda v:b.write(P/'actual-lease-independent-controls.json',v))if tag=='capability'else None
        capability_start_ns=time.monotonic_ns() if cap is not None else None
        if cap is not None:old_id=os.fstat(cap)
        failed=mode in ('malformed','mid-read');before=set(state.glob('actor-*.tsv'));ready=set(state.glob('ready-*'));stop=threading.Event()
        wants=enable and tag not in ('old','warm1','warm-control','native-repair','save-repair','final') and not failed
        serial=(not failed and tag not in ('capability','corrupt','replace')) if not enable else tag in ('old','warm1','native-repair','save-repair','final')
        # All positive candidates and both ordinary warm controls run in separate, unwrapped
        # Cargo invocations and do not first invoke stock Wild in the measured target.
        if enable and tag not in ('edit','native-repair','save-repair'):assert not(wants and serial)
        failed_before=contact.sha_at(out)if failed and out.exists()else None
        if not failed:(state/'coordinate').touch(exist_ok=False)
        if serial:(state/'stock-reference').touch(exist_ok=False)
        if mode:
            marker='mid-output' if mode in ('mid-output','rename-output') else ('mid-read' if mode=='mid-read'else'entry-wait')
            if mode=='exclusive-collision':marker='exclusive-witness'
            (state/marker).touch(exist_ok=False)
        with ThreadPoolExecutor(max_workers=2)as pool:
            target=pool.submit(control,state,stop,stock,llvm,tag,serial,wants,latch,ready)if not failed else None
            if mode in ('mid-output','rename-output'):
                mutate=pool.submit(witness.output_save,state,out,mode=='rename-output')
            elif mode=='exclusive-collision':mutate=pool.submit(witness.output_collision,state,out)
            elif mode=='replace':mutate=pool.submit(witness.replace_before_lookup,state,out)
            else:mutate=pool.submit(donor.witness,state,mode,provider,out)if mode else None
            try:
                if failed:
                    td=P/tag;td.mkdir();b.run(b.CMD,env,td,101);rows=[json.loads(x)for x in (td/'stdout.jsonl').read_bytes().splitlines()];assert rows[-1]=={'reason':'build-finished','success':False}
                    messages=(td/'stderr').read_bytes()+(td/'stdout.jsonl').read_bytes();assert (b'generation changed'if mode=='mid-read'else b'DELIBERATELY')in messages
                else:
                    inv=b.inventory(tag,env,meta);out=w.root/inv['binary'];assert len(inv['executables'])==102 and out.name==contact.BASE
            finally:
                stop.set()
                for live in set(state.glob('actor-*.tsv'))-before:
                    (P/tag/('opened-'+live.name+'.gz')).write_bytes(gzip.compress(live.read_bytes(),mtime=0))
            held=target.result()if target else None;mutation=mutate.result()if mutate else None
        a=donor.outputs(before,tag,state,out,not failed)
        if failed:a['failed_command_output']={'before':failed_before,'after':contact.sha_at(out) if out.exists()else None,'cargo_exit':101}
        if mutation:a['mutation']=mutation
        if held is not None:a['handoff']=held
        rows=gzip.decompress((P/tag/'link-actor.tsv.gz').read_bytes()).decode().splitlines()
        a['native_operations']=[x for x in rows if x.split('\t')[0] in ('ACCEPT','MISS','FRESH-PUBLISH','DOMAINS','WARNING','VERIFIED')]
        if enable:
            if not failed:
                predicted=[r.split('\t')[1:] for r in rows if r.startswith('PROJECTED-GROUP\t')]
                actual=[r.split('\t')[1:] for r in rows if r.startswith('ACTUAL-GROUP\t')]
                groups=held['role']['context']['GROUPINPUT']
                if groups:
                    assert len(groups)==1 and len(predicted)==int(groups[0][3]) and len(predicted)>0
                    if not any(r.startswith('FRESH-PUBLISH\t') for r in rows):assert actual==predicted,(tag,'actual native group plan changed')
                    a['source_group_plan']={'projected':predicted,'actual':actual,'ordered_object_coordinates':groups[0]}
                if held['candidate_requested']:assert groups
            did_reuse=any(x.startswith('FRESH-PUBLISH\t')for x in rows)
            assert did_reuse==(tag in ('warm2','warm-repeat','capability')),(tag,did_reuse,a['native_operations'])
            generations=[r.split('\t')[1:]for r in rows if r.startswith('FRESH-GENERATIONS\t')]
            if did_reuse:
                assert len(generations)==1
                old_dev,old_ino,old_size,old_blocks,old_links,opened_dev,opened_ino,named_dev,named_ino=map(int,generations[0])
                assert old_links==0 and old_size>0 and old_blocks>0 and (opened_dev,opened_ino)==(named_dev,named_ino)!=(old_dev,old_ino)
                a['fresh_inode']={'held_old':[old_dev,old_ino,old_size,old_blocks*512,old_links],'newly_created':[opened_dev,opened_ino],'named':[named_dev,named_ino]}
            if did_reuse:assert held['candidate_requested'] and not serial and sum(x.startswith('ACCEPT\t')for x in rows)==1
            if tag in ('edit','earlier','four','native-repair'):assert not held['candidate_requested'],tag
            if tag=='edit':assert held['role']['key']!=latch['key'], 'an ordinary real Ruff edit collided with the OLD latch'
            if tag in ('corrupt','replace','mid-output','rename-output','exclusive-collision'):
                assert held['candidate_requested'] and any(x.startswith('MISS\toutput-')for x in rows),(tag,a['native_operations'])
        if not failed:
            assert held and (enable or not held['candidate_requested']);native=elf_container.inspect(out,llvm);b.write(P/(tag+'-source-container.json.gz'),native)
            assert native['sha256']==a['sha256'] and native['buildid']==native['zeroed_complete_buildid']
            tombstone=out.with_suffix('.delete')
            observed_tombstone=None
            try:
                opened=tombstone.stat();observed_tombstone=[opened.st_dev,opened.st_ino,opened.st_size,512*opened.st_blocks]
            except FileNotFoundError:pass
            until=time.monotonic()+45;begin=time.monotonic_ns()
            while tombstone.exists()and time.monotonic()<until:time.sleep(.002)
            assert not tombstone.exists()
            a['transient_output_cleanup']={'path':str(tombstone),'present_on_first_check':observed_tombstone,'additional_wait_ns':time.monotonic_ns()-begin}
            a['canonical_storage']={'path':str(out),'size':out.stat().st_size,'links':out.stat().st_nlink,'allocated':512*out.stat().st_blocks,'old_delete_entry_present':False}
            if enable and tag in ('warm2','capability','final'):
                a['canonical_storage']['same_image_in_both_output_roots']=stored_generations(out,native)
            rh=json.loads((P/tag/'resources.json').read_bytes());hw=json.loads((P/tag/'hardware.json').read_bytes())
            a['ordinary_clock']={'seconds':rh['seconds'],'retired_user':hw['instructions'],'enabled':hw['enabled'],'running':hw['running'],'minimum_free_memory':rh['minimum_mem'],'minimum_free_storage':rh['minimum_disk'],'serial_signed_control_ran':serial,
                                 'command_elapsed_ns':int((P/tag/'hardware.json.elapsed-ns').read_text()),
                                 'coordinator_thread':held['coordinator_clock'],
                                 'cargo_and_coordinator_user_instructions':None if serial else hw['instructions']+held['coordinator_clock']['instructions']}
            if serial:
                assert len({r['sha256']for r in held['signed_repetitions']})==1,('signed/signed mismatch',tag,held['signed_repetitions'])
                s=json.loads(gzip.decompress((P/(tag+'-signed-container.json.gz')).read_bytes()))
                a['signed_relationship']=elf_container.compare(s,native)
                if s['sha256']!=native['sha256']:
                    # Both artifacts are distinct real emissions. Write their complete section
                    # and complement record before rejecting, including the signed verdict.
                    b.write(P/(tag+'-typed-difference.json'),a)
                    raise AssertionError('signed/source DIFFERED ON THE SAME LIVE LINK: '+tag)
            if tag=='edit':signed_reference=native
            if tag in ('old','edit','warm1') and enable:
                role=held['role'];image=role['context']['ADMISSION'][0][1]
                assert held['grammar'] and native['sha256']==contact.LITERALS['old' if tag=='old' else 'new']
                if tag=='warm1':
                    assert role['context']['ADMISSION'][0][0]=='true' and role['context']['DOMAINS']==[['true','true','1']]
                latch={'key':role['key'],'image':image,'output':a['emitted'][3],'size':native['size'],'from_full_cargo':tag}
                a['new_latch']=latch
            if signed_reference and tag!='four':a['prior_clean_relationship']=elf_container.compare(signed_reference,native)
            if tag in ('old','edit','warm1','warm2','warm-repeat','warm-control','mid-output','rename-output','capability','corrupt','replace','earlier'):assert native['sha256']==contact.LITERALS['old'if tag=='old'else'new']
            if cap is not None:
                try:
                    assert (old_id.st_dev,old_id.st_ino)!=(native['dev'],native['ino'])
                    # A regular old read would deny a write lease, but O_PATH is invisible to
                    # the exclusive lease. Exercise this actual stale capability after publishing.
                    fd=os.open('/proc/self/fd/'+str(cap),os.O_WRONLY);assert os.pwrite(fd,b'\0\0',18)==2;os.close(fd)
                    assert w.hf(out)==native['sha256'];a['old_capability']=[old_id.st_dev,old_id.st_ino,old_id.st_size,old_id.st_blocks,os.fstat(cap).st_nlink]
                finally:
                    os.close(cap);a['held_old_capability_ns']=time.monotonic_ns()-capability_start_ns
            if tag=='four':
                t=subprocess.run([out,'--list'],cwd=w.work/'crates/ty_server',env=env,capture_output=True);assert t.returncode==83 and not t.stdout;a['exit']=t.returncode
            else:assert b.verdict(out,tag+'-verdict',env,0)==contact.LITERALS['list']
        b.write(P/(tag+'-complete.json'),a);result[tag]=a
        for f in ('exclusive-witness','fresh-opening','fresh-continue','coordinate','stock-reference','mid-output','output-half','output-continue','mid-read','entry-wait','entry-ready','read-first-half','entry-continue','continue-read'):(state/f).unlink(missing_ok=True)
        for f in state.glob('local-env-*'):f.unlink()
    if enable:
        # Dispose only this worker's own isolated build state before the unmodified
        # SDK rebuilds NEW from an empty history at exactly the same canonical paths.
        signed_path=w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
        tmp=signed_path.parent/'qa-put-back-exact-stock';shutil.copy2(stock,tmp);os.replace(tmp,signed_path)
        assert w.hf(signed_path)==donor.WILD
        old_logs=set(state.glob('actor-*.tsv'))
        for isolated in (w.target,w.shared,w.home):
            assert isolated.parent==w.root and isolated.is_dir()and not isolated.is_symlink();shutil.rmtree(isolated)
        b.PHYSICAL.clear();assert b.inputs(env)==json.loads(gzip.decompress((P/'registry.json.gz').read_bytes()))
        clean=b.inventory('signed-independent-new',env,meta);p=w.root/clean['binary']
        assert old_logs==set(state.glob('actor-*.tsv'))and len(clean['executables'])==102
        assert clean['binary']==str(out.relative_to(w.root))and b.verdict(p,'signed-independent-new-verdict',env,0)==contact.LITERALS['list']
        native=elf_container.inspect(p,llvm);b.write(P/'signed-independent-new-container.json.gz',native)
        assert native['sha256']==contact.LITERALS['new']==result['warm2']['sha256']==result['edit']['sha256']
        assert stored_generations(p,native)==[str(p)]
        result['signed-independent-new']={'sha256':native['sha256'],'canonical':str(p),'source':b.NEW,'executable_count':102,'signed_wild':w.hf(signed_path)}
        for stage in ('signed-untouched-warm1','signed-untouched-warm2'):
            genuine=b.inventory(stage,env,meta);full=w.root/genuine['binary']
            assert len(genuine['executables'])==102 and full==p
            assert old_logs==set(state.glob('actor-*.tsv')) and w.hf(signed_path)==donor.WILD
            assert b.verdict(full,stage+'-verdict',env,0)==contact.LITERALS['list']
            image=elf_container.inspect(full,llvm);b.write(P/(stage+'-container.json.gz'),image)
            assert image['sha256']==native['sha256']==result['warm2']['sha256']
            raw=json.loads((P/stage/'hardware.json').read_bytes());res=json.loads((P/stage/'resources.json').read_bytes())
            result[stage]={'sha256':image['sha256'],'source':b.NEW,'source_native_role_count':0,'executable_count':102,'stock_wild':w.hf(signed_path),'ordinary_clock':{'retired_user':raw['instructions'],'enabled':raw['enabled'],'running':raw['running'],'seconds':res['seconds'],'command_elapsed_ns':int((P/stage/'hardware.json.elapsed-ns').read_text())}}
            b.write(P/(stage+'-complete.json'),result[stage])
    assert not list(P.rglob('*.elf*'));b.write(P/'complete.json',result)
if __name__=='__main__':main(sys.argv[1:]==['--enable-one-proved-link'])
