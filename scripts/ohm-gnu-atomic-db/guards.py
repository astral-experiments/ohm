"""Probe a typed positive or adjacent hostile assembler form, native bundling and real input changes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-gnu-syscall')]
import sdk
from sdk import census
from direct import CFG, BEFORE
MARKERS={'hard':census.HARD,'v2':census.SOFT,'v1':census.OLD}
ADDED={'atomic_loop','atomic_feature'}
EXTRA={'atomic_file','atomic_other_extension','atomic_literal'}
HOSTILE='ordinary macro_inside global_shadow same_line feature_tail label_include label_expression symbol relocation const_label explicit_width other_options naked'.split()
PAYLOAD=b'\xc1\x7aOHM_SUPPRESSED_DIRECT_AARCH64_FILE\x00\xf1\xb2\x02'
T=census.TARGET

def envs(root,stable):
    proxy=Path(shutil.which('rustup')).resolve(strict=True)
    home=root/'home';home.mkdir()
    rustup=root/'rustup';(rustup/'toolchains').mkdir(parents=True)
    (rustup/'toolchains/ohm').symlink_to(stable, target_is_directory=True)
    bins=root/'bin';bins.mkdir()
    for tool in ('cargo','rustc','rustup'):(bins/tool).symlink_to(proxy)
    return {'PATH':str(bins)+':/usr/local/bin:/usr/bin:/bin','HOME':str(home),'RUSTUP_HOME':str(rustup),
            'CARGO_HOME':str(root/'cargo-home'),'CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'shared'),
            'CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER':'/usr/bin/aarch64-linux-gnu-gcc','CARGO_NET_OFFLINE':'true',
            'RUSTUP_AUTO_INSTALL':'0','LC_ALL':'C','TZ':'UTC'}

def direct(root,out,env,role):
    (root/'payload.bin').write_bytes(PAYLOAD)
    (root/'nested.s').write_text('.incbin "payload.bin"\n')
    data={}
    base=['rustc','+ohm','--target',T,'-Zohm-check-relink-inputs','-C','codegen-units=1']
    original=HERE/'fixtures/gnu_aarch64.rs'
    assert subprocess.check_output(['git','hash-object',original],text=True).strip()==sdk.SOURCE['candidate']['paths']['tests/run-make/ohm-checked-dep-info/gnu_aarch64.rs']
    for family,source,cases in [('product',original,[*CFG,*sorted(ADDED|EXTRA)]),
                                ('hostile',HERE/'fixtures/hostile.rs',HOSTILE)]:
        for name in cases:
            folder=out/family/name;folder.mkdir(parents=True)
            archive=folder/'libguard.rlib'
            cmd=[*base,source,'--cfg',name,'--emit=link,dep-info=-','-o',archive]
            q=subprocess.run(cmd,cwd=root,env=env,capture_output=True)
            census.blob(folder/'stdout.gz',q.stdout);census.blob(folder/'stderr.gz',q.stderr)
            assert q.returncode==0,(family,name,q.stderr.decode()[-1000:])
            marker=census.marker(q.stdout)
            accepted=(name in BEFORE|{'syscall'} or (name in ADDED and role=='C')) if family=='product' else name=='ordinary' and role=='C'
            assert marker==('v2' if accepted else 'hard'),(role,family,name,marker,accepted)
            raw=archive.read_bytes()
            included=PAYLOAD in raw
            if family=='hostile' and name in ('same_line','feature_tail','label_include','macro_inside'):
                assert included,(family,name)
            # Global macro definitions conservatively veto the crate even if the assembler uses a separate MCContext.
            data[family+'/'+name]={'marker':marker,'archive':hashlib.sha256(raw).hexdigest(),'embedded_payload':included}
            archive.unlink()
    # Use a real native object, so whether it made it into the Rust archive can be checked independently.
    obj=root/'atomic_provider.o'
    subprocess.run(['aarch64-linux-gnu-gcc','-x','c','-c','-','-o',obj],input=b'int ohm_atomic_external(void){return 17;}\n',check=True)
    native=root/'libatomic_check.a'
    subprocess.run(['aarch64-linux-gnu-ar','rcsD',native,obj],check=True)
    for label,kind in [('default','static'),('bundle','static:+bundle'),('external','static:-bundle')]:
        d=out/('native-'+label);d.mkdir()
        archive=d/'libprobe.rlib'
        cmd=[*base,original,'--cfg','atomic_loop','-L','native='+str(root),'-l',kind+'=atomic_check','--emit=link,dep-info=-','-o',archive]
        q=subprocess.run(cmd,cwd=root,env=env,capture_output=True)
        census.blob(d/'stdout.gz',q.stdout);census.blob(d/'stderr.gz',q.stderr)
        assert q.returncode==0,(label,q.stderr[-650:])
        marker=census.marker(q.stdout)
        contained=obj.read_bytes() in archive.read_bytes()
        accept=role=='C' and label=='external'
        assert marker==('v2' if accept else 'hard') and contained==(label!='external'),(label,marker,contained)
        data['native/'+label]={'marker':marker,'embedded_object':contained}
        archive.unlink()
    census.save(out/'direct.json',data)

def history(root,out,env):
    src=root/'asm-app';(src/'src').mkdir(parents=True)
    (src/'Cargo.toml').write_text('[package]\nname="qa_atomic_file_history"\nversion="0.0.0"\nedition="2021"\n[workspace]\n')
    inc=src/'case.inc';payload=src/'input.bin'
    quoted=json.dumps('.include "'+str(inc)+'"')
    (src/'src/main.rs').write_text('''fn main() {
        let answer: u64;
        unsafe { core::arch::asm!("b 2f", ".p2align 3", "3:", INCLUDE, "2:",
            "adr {v}, 3b", "ldar {v}, [{v}]", v=out(reg) answer, options(nostack, preserves_flags)); }
        println!("{answer}");
    }'''.replace('INCLUDE',quoted))
    original='.incbin "'+str(payload)+'"\n'
    inc.write_text(original);payload.write_bytes(struct.pack('<Q',17));stamp=payload.stat()
    census.command(['cargo','+ohm','generate-lockfile','--offline'],src,env)
    cmd=['cargo','+ohm','build','--bin','qa_atomic_file_history','--target',T,'--locked','--offline','--message-format=json']
    facts={}
    for state,want in [('cold',17),('same-inode-mtime',29),('malformed',None),('missing',None),('restored',41)]:
        if state=='same-inode-mtime':
            payload.write_bytes(struct.pack('<Q',29));os.utime(payload,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            assert (payload.stat().st_size,payload.stat().st_ino,payload.stat().st_mtime_ns)==(stamp.st_size,stamp.st_ino,stamp.st_mtime_ns)
        if state=='malformed':inc.write_text('.error "OHM_GNU_ASM_MALFORMED"\n')
        if state=='missing':inc.write_text(original);payload.unlink()
        if state=='restored':payload.write_bytes(struct.pack('<Q',41))
        rows={}
        for variant in ('warm','empty'):
            cenv=env if variant=='warm' else env|{'CARGO_TARGET_DIR':str(root/('empty-target-'+state)),
                                                  'CARGO_BUILD_BUILD_DIR':str(root/('empty-shared-'+state))}
            d,msg,events=census.trace_build(state+'-'+variant,root,out,src,cenv,cmd,101 if want is None else 0)
            full=[r for r in events['rustcs'] if r['crate']=='qa_atomic_file_history' and not r['link_only']]
            assert len(full)==1,(state,variant,events)
            if want is None:
                stderr=gzip.decompress((d/'stderr.gz').read_bytes())
                diag=stderr+b'\n'+b'\n'.join(json.dumps(v).encode() for v in msg)
                text=b'OHM_GNU_ASM_MALFORMED' if state=='malformed' else b'input.bin'
                assert text in diag
                rows[variant]={'exit':101,'diagnostic':text.decode()}
            else:
                exe,=[Path(m['executable']) for m in msg if m['reason']=='compiler-artifact' and m.get('executable')]
                run=subprocess.run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',exe],env=cenv,capture_output=True)
                assert run.returncode==0 and run.stdout==f'{want}\n'.encode()
                rows[variant]={'exit':0,'qemu':want,'elf':census.sha(exe),'linkers':[r['path'] for r in events['link_tools']]}
                assert any(Path(f).name=='ld' for f in rows[variant]['linkers'])
        assert rows['warm'].get('qemu')==rows['empty'].get('qemu') and rows['warm']['exit']==rows['empty']['exit']
        facts[state]=rows
    census.save(out/'file-history.json',facts)

def main():
    out=Path(os.environ['RUNNER_TEMP'])/'atomic-file-guards';out.mkdir()
    for role in 'PC':
        root=out/role;root.mkdir();r=root/'receipts';r.mkdir()
        sdkdir=sdk.switch(role);census.qualify.rt.SDK=sdkdir
        env=envs(root,sdkdir)
        direct(root,r,env,role)
        history(root,r,env)
    census.save(out/'terminal.json',{'roles':['P','C'],'portable_file_histories':True,'positive_forms':sorted(ADDED)})
if __name__=='__main__':main()
