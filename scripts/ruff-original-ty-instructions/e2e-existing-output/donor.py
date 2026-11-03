"""Let the actual private source Wild parse and emit every byte on every ordinary Cargo link."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import contact
import prepare_source
b=contact.study;w=contact.w;P=b.PROOF
SOURCE_NAMES=('libwild/src/fs.rs','libwild/src/input_data.rs','libwild/src/lib.rs','libwild/src/frozen.rs')
WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
def source_actor(env):
    src=Path(os.environ['GITHUB_WORKSPACE'])/'wild-source';paths=prepare_source.prepare(src);assert set(paths)==set(SOURCE_NAMES)
    kit=w.root/'source-tool';kit.mkdir()
    command=['cargo','+ohm','-Zohm-defaults=no','build','--release','--locked','-p','wild-linker','--bin','wild','-j4']
    isolated=dict(env,WILD_QA_ROOT=str(w.root),CARGO_HOME=str(kit/'home'),CARGO_TARGET_DIR=str(kit/'target'),CARGO_BUILD_BUILD_DIR=str(kit/'shared'))
    online=dict(isolated);online.pop('CARGO_NET_OFFLINE',None)
    subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=src,env=online,check=True,timeout=900)
    with(P/'source.out').open('xb')as so,(P/'source.err').open('xb')as se:
        proc=subprocess.run(command,cwd=src,env=isolated,stdout=so,stderr=se,timeout=1800)
    assert proc.returncode==0,(P/'source.err').read_text()[-2600:]
    actor=kit/'target/release/wild';path=w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
    assert w.hf(path)==WILD and not path.is_symlink() and path.resolve().is_relative_to(w.sdk)
    pending=path.parent/'qa-linker-install';shutil.copy2(actor,pending);os.replace(pending,path)
    record={'stock':WILD,'source_actor':w.hf(path),'llvm':None,'src':{name:w.hf(src/name)for name in SOURCE_NAMES},'upstream':prepare_source.BASE,'lock':w.hf(src/'Cargo.lock'),'command':command,'real_target':str(path)}
    b.write(P/'actor.json',record)
    return record

def full_b3(path):
    lib,=list((w.sdk/'lib').glob('libLLVM.so.*'))
    api=ctypes.CDLL(str(lib));ptr=ctypes.c_void_p
    h=api.llvm_blake3_hasher_init;h.argtypes=[ptr];h.restype=None
    u=api.llvm_blake3_hasher_update;u.argtypes=[ptr,ptr,ctypes.c_size_t];u.restype=None
    f=api.llvm_blake3_hasher_finalize;f.argtypes=[ptr,ptr,ctypes.c_size_t];f.restype=None
    state=(ctypes.c_uint64*512)();out=(ctypes.c_ubyte*32)();h(state);f(state,out,32)
    assert bytes(out).hex()=='af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262'
    h(state)
    with path.open('rb')as file:
        while block:=file.read(1024*1024):u(state,block,len(block))
    f(state,out,32)
    return bytes(out).hex()

def outputs(before,tag,state,bin_path,successful):
    names=sorted(set(state.glob('actor-*.tsv'))-before);td=P/tag
    audit=[(path,path.read_text().splitlines())for path in names];assert len(audit)==1,[(p,len(ls))for p,ls in audit]
    path,lines=audit[0];(td/'link-actor.tsv.gz').write_bytes(gzip.compress(path.read_bytes(),mtime=0))
    err=[row for row in lines if row.startswith('REFUSED\t')]
    if not successful:
        assert 'VERIFIED'not in lines and not any(l.startswith('EMITTED\t')for l in lines),(tag,err)
        return {'successful':False,'refusals':err}
    frozen=[x.split('\t')[1:]for x in lines if x.startswith('FROZEN\t')]
    used=[x.split('\t')[1:]for x in lines if x.startswith('USED\t')]
    emits=[x.split('\t')[1:]for x in lines if x.startswith('EMITTED\t')]
    assert len(frozen)==len(used)==409 and len(emits)==1 and lines.count('VERIFIED')==1 and not err,(tag,len(frozen),len(used),emits,err)
    assert set(row[-1]for row in frozen)==set(row[-1]for row in used)and len(set(row[-1]for row in frozen))==409
    records={r[-1]:(int(r[2]),r[3])for r in frozen};assert all(records[r[-1]]==(int(r[1]),r[2])for r in used)
    asserts=[int(r[0])for r in used];assert asserts==list(range(409))
    emit=emits[0];s=bin_path.lstat();assert str(bin_path)==emit[-1] and (s.st_dev,s.st_ino,s.st_size)==tuple(map(int,emit[:3]))
    disk=full_b3(bin_path);assert disk==emit[3]
    return {'successful':True,'emitted':emit,'sha256':w.hf(bin_path),'n':len(frozen),'bytes':sum(v[0]for v in records.values()),'ordered_payload_root':b.sha(b''.join(struct.pack('<Q',int(v[1]))+bytes.fromhex(v[2])for v in used)),'mode_roster':sorted({r[3]for r in used})}

def witness(state,mode,provider,binary,symbol_input=None):
    mid=mode=='mid-read';ready=state/('read-first-half' if mid else 'entry-ready')
    deadline=time.monotonic()+120
    while not ready.exists():
        if time.monotonic()>deadline:raise RuntimeError('actual e2e linker did not reach '+mode)
        time.sleep(.01)
    path=Path(ready.read_bytes().decode());assert path.name=='symbols.o'and path.parent.parent==binary.parent
    raw=path.parent/'raw-dylibs';record={'mode':mode,'symbol_before':w.hf(path)}
    if mode in ('earlier','four','malformed'):
        raw.mkdir(exist_ok=True);dest=raw/'libutil.a';assert not dest.exists()
        if mode=='malformed':dest.write_bytes(b'DELIBERATELY MALFORMED NATIVE PROVIDER\n')
        else:shutil.copyfile(provider,dest)
        record['provider']=w.hf(dest)
    if mode in ('mid-read','four'):
        old=path.read_bytes();assert len(old)==(39760 if symbol_input is None else symbol_input[0]) and old.count(b'\0main\0')==1
        if symbol_input is not None:
            assert full_b3(path)==symbol_input[1]
            record['genuine_symbols_input']=[len(old),symbol_input[1]]
        new=old.replace(b'\0main\0',b'\0zzQA\0');st=path.stat()
        path.write_bytes(new);os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns));t=path.stat()
        assert (t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns)==(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns) and t.st_ctime_ns!=st.st_ctime_ns
        record['changed_offsets']=[i for i,(x,y)in enumerate(zip(old,new))if x!=y];assert len(record['changed_offsets'])==4
    if mode=='replace':
        # Atomically replace the canonical name with a different, tiny regular file. The QA
        # never saves the old ELF under another persistent name.
        old=binary.stat();replacement=binary.parent/'qa-short-replacement';assert not replacement.exists()
        replacement.write_bytes(b'OHM invalid substituted executable\n');os.replace(replacement,binary)
        record['displaced']=[old.st_dev,old.st_ino,old.st_size];record['replacement_sha']=w.hf(binary)
    record['symbol_after']=w.hf(path);(state/('continue-read'if mid else 'entry-continue')).touch(exist_ok=False)
    return record

def text_flip(binary):
    with binary.open('r+b')as f:
        header=struct.unpack('<16sHHIQQQIHHHHHH',f.read(64));off,ent,names=header[6],header[11],header[13]
        f.seek(off+ent*names);name_section=struct.unpack('<IIQQQQIIQQ',f.read(64));f.seek(name_section[4]);names_raw=f.read(name_section[5])
        loc=None
        for i in range(header[12]):
            f.seek(off+ent*i);sec=struct.unpack('<IIQQQQIIQQ',f.read(64))
            if names_raw[sec[0]:].split(b'\0',1)[0]==b'.text':
                assert sec[5]>1000 and loc is None;loc=sec[4]+sec[5]//2
        assert loc is not None
        f.seek(loc);x=f.read(1);f.seek(loc);f.write(bytes([x[0]^1]))
    return loc
def provider_file():
    root=w.root/'earlier-native';root.mkdir();src=root/'guard.s';obj=root/'guard.o';lib=root/'libutil.a'
    src.write_text('.text\n.globl zzQA\n.type zzQA,@function\nzzQA: ret\n.type qa_force_exit,@function\nqa_force_exit: mov $83,%edi\n mov $231,%eax\n syscall\n ud2\n.section .init_array,"aw",@init_array\n.p2align 3\n.quad qa_force_exit\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['/usr/bin/as','--64','-o',obj,src],check=True);subprocess.run(['/usr/bin/ar','crD',lib,obj],check=True)
    return lib

def main():
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']
    assert shutil.disk_usage(w.root).free>45*2**30;w.guard();b.save_elf=w.hf
    b.write(P/'registration.json',{'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'sdk':b.SPEC['sdk_manifest'],'reference':contact.LITERALS,'scope':'One normal GNU workflow. Always run full Wild. Every output verified against actual immutable inputs and fresh emission.'})
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2',HERE.parent/'whole_count.c','-o',w.root/'whole_count'],check=True)
    env=w.install();state=w.root/'native-donor-state';state.mkdir();source_actor(env);b.select(b.OLD);b.write(P/'registry.json.gz',b.inputs(env));provider=provider_file()
    meta=json.loads(subprocess.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env));assert len(meta['workspace_default_members'])==55
    out=None;result={}
    for tag,mode in [('old',None),('edit',None),('warm1',None),('warm2',None),('earlier','earlier'),('four','four'),('malformed','malformed'),('native-repair',None),('save','mid-read'),('save-repair',None),('corrupt',None),('replaced','replace'),('final',None)]:
        if tag=='edit':
            b.select(b.NEW);assert b.verdict(out,'withheld-old-fails',env,101)==contact.LITERALS['list']
        failed=mode in ('malformed','mid-read');previous=set(state.glob('actor-*.tsv'));flip=None
        if tag=='corrupt':
            st=out.stat();flip=text_flip(out);os.utime(out,ns=(st.st_atime_ns,st.st_mtime_ns));assert w.hf(out)!=contact.LITERALS['new']
        if mode:(state/('mid-read' if mode=='mid-read' else 'entry-wait')).touch(exist_ok=False)
        with ThreadPoolExecutor(max_workers=1)as pool:
            co=pool.submit(witness,state,mode,provider,out)if mode else None
            if failed:
                td=P/tag;td.mkdir();b.run(b.CMD,env,td,101)
                rows=[json.loads(x)for x in (td/'stdout.jsonl').read_bytes().splitlines()];assert rows[-1]=={'reason':'build-finished','success':False}
                messages=(td/'stderr').read_bytes()+(td/'stdout.jsonl').read_bytes()
                assert (b'generation changed'if mode=='mid-read'else b'DELIBERATELY')in messages
            else:
                inv=b.inventory(tag,env,meta);out=w.root/inv['binary']
                assert out.name==contact.BASE and len(inv['executables'])==102
            mutation=co.result()if co else None
        row=outputs(previous,tag,state,out,not failed)
        if mutation:row['mutation']=mutation
        if flip is not None:row['corrupt_text_offset']=flip
        if not failed:
            if mode=='four':
                test=subprocess.run([out,'--list'],env=env,cwd=w.work/'crates/ty_server',capture_output=True)
                assert test.returncode==83 and not test.stdout and row['sha256']!=contact.LITERALS['new'];row['exit']=test.returncode
            else:
                # Record the genuine digest even on a different source factory. This explicit
                # hard guard precedes every future reuse decision.
                prior=contact.LITERALS['old'if tag=='old'else 'new']
                b.write(P/tag/'disk-output-verdict.json',{'actual':row['sha256'],'signed_independent_reference':prior,'equal':row['sha256']==prior})
                assert b.verdict(out,tag+'-verdict',env,0)==contact.LITERALS['list']
                if row['sha256']!=prior:
                    b.write(P/'refused.json',{'phase':tag,'actual':row,'reason':'complete source output differs from signed reference'});raise ValueError('full signed-reference hash differs')
        for name in ('mid-read','entry-wait','entry-ready','read-first-half','entry-continue','continue-read'):
            (state/name).unlink(missing_ok=True)
        result[tag]=row;b.write(P/(tag+'-donor.json'),row)
    assert result['warm1']['ordered_payload_root']==result['warm2']['ordered_payload_root']
    assert result['earlier']['ordered_payload_root']!=result['warm1']['ordered_payload_root'] and result['four']['ordered_payload_root']!=result['earlier']['ordered_payload_root']
    assert result['save']['refusals'] and not list(P.glob('*.elf*'))
    b.write(P/'complete.json',result)
if __name__=='__main__':main()
