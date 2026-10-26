#!/usr/bin/env python3
"""Count a six-Cargo, two-rustc and Wild comparison after both native oracle preflights."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess


def load_module(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native=load_module('native_oracle','full-toolchain-preflight.py')
portable=load_module('portable_measure','measure.py' if Path(__file__).with_name('measure.py').exists() else 'replay-portable.py')
NAMES=['parent','stack']


def snapshot(receipt):
    h=hashlib.sha256()
    hashed={}
    entries=0
    bytes_read=0
    for p in sorted(receipt.rglob('*')):
        rel=p.relative_to(receipt).as_posix()
        if p.is_symlink(): item=('link',rel,os.readlink(p))
        elif p.is_file():
            st=p.stat()
            key=st.st_dev,st.st_ino
            if key not in hashed:
                hashed[key]=native.sha(p)
                bytes_read+=st.st_size
            item=('file',rel,st.st_size,hashed[key])
        elif p.is_dir():item=('dir',rel)
        else:raise ValueError(('unexpected snapshot entry',rel))
        h.update(json.dumps(item,separators=(',',':')).encode());h.update(b'\n')
        entries+=1
    return dict(sha256=h.hexdigest(),entries=entries,unique_file_bytes=bytes_read)


class Holdout:
    def __init__(self, args):
        self.style=args.style
        self.mode=args.mode
        self.repo=args.ruff.resolve(strict=True)
        self.state=args.state.resolve()
        self.out=args.output.resolve()
        self.spec=json.loads(args.spec.read_text())
        self.active=self.state/'active'
        self.store=self.state/'arms'
        self.current=None
        self.runtime=(self.state/'runtime' if self.style=='prebuilt' else self.active/'toolchain')
        self.linker=self.state/'ld.bfd' if self.style=='prebuilt' else self.runtime/native.WILD
        self.clang=self.state/'clang'
        self.rustup=self.state/'rustup'
        rel,old,new,self.unit,self.command,self.units,self.exes,self.budget=native.SELECTION[self.mode]
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.repo,text=True).strip()==native.RUFF
        assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=self.repo)
        self.source=self.repo/rel
        original=self.source.read_bytes()
        assert original.count(old)==1 and new not in original
        self.contents={'original':original,'changed':original.replace(old,new)}
        self.env=dict(os.environ,RUSTUP_HOME=str(self.rustup),RUSTUP_AUTO_INSTALL='0',
                      CARGO_HOME=str(self.active/'cargo-home'),CARGO_TARGET_DIR=str(self.active/'target'),
                      CARGO_BUILD_BUILD_DIR=str(self.active/'shared'),CARGO_BUILD_JOBS='4',CARGO_TERM_COLOR='never',
                      CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(self.clang),
                      CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST='all',CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST='all',
                      SSL_CERT_FILE='/etc/ssl/certs/ca-certificates.crt',SSL_CERT_DIR='/etc/ssl/certs')
        assert not any(self.env.get(k) for k in ['RUSTC','RUSTC_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','OHM_COUNT_OUT'])
        if self.style=='prebuilt':
            self.env.update(RUSTC=str(self.runtime/'bin/rustc'),RUSTC_WRAPPER=str(self.state/'compiler-wrapper'),
                            OHM_SYSROOT=str(self.runtime),OHM_PACKAGE=self.unit)
        self.oracle={}

    def load_oracles(self):
        self.oracle={e:json.loads((self.out/('parent-'+e)/'result.json').read_text()) for e in self.contents}

    def selected_driver(self, arm):
        if self.style=='full':return self.runtime/native.DRIVER
        return self.state/'drivers'/arm/Path(native.DRIVER).name

    def verify(self,arm):
        subject=self.spec['arms'][arm]
        for path,key in [(self.runtime/'bin/cargo','cargo'),(self.linker,'wild'),(self.selected_driver(arm),'driver')]:
            assert native.sha(path)==subject[key]['sha256'],(path,key)
        assert native.sha(self.runtime/'bin/rustc')==self.spec['common_hashes']['bin/rustc']
        if self.style=='prebuilt':
            assert native.sha(self.runtime/native.DRIVER)==self.spec['arms']['parent']['driver']['sha256']

    def move(self,arm):
        if self.current==arm:return
        if self.current:self.active.rename(self.store/self.current)
        (self.store/arm).rename(self.active)
        self.current=arm
        if self.style=='prebuilt':
            subject=self.spec['arms'][arm]
            for path,key in [(self.runtime/'bin/cargo','cargo'),(self.linker,'wild')]:
                if native.sha(path)!=subject[key]['sha256']:
                    portable.replace(Path(subject[key]['path']),path)
            self.env['OHM_DRIVER_DIR']=str(self.selected_driver(arm).parent)
        self.verify(arm)
        native.check_compilers(self.out,arm,self.runtime,self.selected_driver(arm))

    def restore(self):
        if self.source.read_bytes()==self.contents['changed']:
            self.source.write_bytes(self.contents['original'])
        if self.current and self.active.exists():
            self.active.rename(self.store/self.current)
        self.current=None

    def invoke(self,label,arm,edit,count):
        self.move(arm)
        before=self.source.read_bytes()
        assert before in self.contents.values()
        if before!=self.contents[edit]:self.source.write_bytes(self.contents[edit])
        directory=self.out/label
        prefix=[]
        if count!='native':
            prefix=['valgrind','--tool=cachegrind','--cache-sim=no','--branch-sim=no','--trace-children=yes',
                    '--verbose',*([f'--trace-children-skip={portable.SKIP}'] if count=='parent' else []),
                    f'--cachegrind-out-file={directory}/guest.%p',f'--log-file={directory}/vg.%p']
        inputs={'cargo':self.runtime/'bin/cargo','wild':self.linker}
        before_inputs=native.identities(inputs)
        native.check_compilers(self.out,arm,self.runtime,self.selected_driver(arm))
        result=native.capture(self.repo,self.env,self.command,directory,self.state,prefix=prefix)
        native.check_compilers(self.out,arm,self.runtime,self.selected_driver(arm))
        assert native.identities(inputs)==before_inputs,(label,'cargo or linker changed during invocation')
        assert len(result['graph'])==self.units and len(result['outputs'])==self.exes
        counts={}
        if count=='full':
            counts=portable.profiles(directory,self.linker)
            profile,=[p for p in directory.glob('guest.*') if
                      any(line.startswith('cmd: ') and Path(line[5:].split()[0]).name=='rustc'
                          for line in p.open() if line.startswith('cmd: '))]
            mappings={Path(line.split('Reading syms from ',1)[1].strip()).resolve()
                      for line in (directory/f'vg{profile.suffix}').read_text().splitlines()
                      if 'Reading syms from ' in line and line.rstrip().endswith('/'+Path(native.DRIVER).name)}
            assert mappings=={self.selected_driver(arm).resolve()},(label,mappings,self.selected_driver(arm))
        return result,counts

    def assert_oracle(self,edit,result,label):
        diff=native.compare(self.oracle[edit],result)
        if diff:
            native.save(self.out/'failed-oracle.json',{'label':label,'edit':edit,'differences':diff})
            raise RuntimeError(('unequal native oracle',label,[json.loads(z['target'])[1] for z in diff if 'target' in z][:8]))

    def freeze(self):
        assert self.style=='prebuilt'
        assert shutil.disk_usage(self.state.parent).free >= (2*self.budget+native.FLOOR_GIB)*native.GIB
        self.state.mkdir()
        self.out.mkdir(parents=True)
        self.store.mkdir()
        (self.store/'parent').mkdir()
        (self.store/'parent'/'cargo-home').mkdir()
        (self.store/'parent'/'cargo-home'/'registry').symlink_to(Path(self.spec['registry']).resolve(strict=True))
        self.runtime.mkdir()
        common=Path(self.spec['runtime']).resolve(strict=True)
        subprocess.run(['cp','-a','--reflink=auto',str(common)+'/.' ,self.runtime],check=True)
        for path,digest in self.spec['common_hashes'].items():assert native.sha(self.runtime/path)==digest
        assert (self.runtime/'bin/rustc').stat().st_nlink==1
        for arm in NAMES:
            driver=self.selected_driver(arm)
            driver.parent.mkdir(parents=True)
            native.install(Path(self.spec['arms'][arm]['driver']['path']),driver)
            assert native.sha(driver)==self.spec['arms'][arm]['driver']['sha256']
        for path,kind in [(self.runtime/'bin/cargo','cargo'),(self.runtime/native.DRIVER,'driver'),(self.linker,'wild')]:
            native.install(Path(self.spec['arms']['parent'][kind]['path']),path)
        (self.rustup/'toolchains').mkdir(parents=True)
        (self.rustup/'settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
        (self.rustup/'toolchains'/'ohm').symlink_to(self.runtime)
        real=shutil.which('clang');assert real
        self.clang.write_text('#!/bin/sh\nexec '+shlex.quote(real)+' "$@" '+shlex.quote('--ld-path='+str(self.linker))+' -Wl,--no-fork\n')
        self.clang.chmod(0o755)
        wrapper=Path(self.spec['wrapper']['path'])
        assert native.sha(wrapper)==self.spec['wrapper']['sha256']
        native.install(wrapper,self.state/'compiler-wrapper')
        self.move('parent')
        version=subprocess.check_output(['rustc','+ohm','-Vv'],env=self.env,text=True)
        assert self.spec['rustc_commit'] in version and 'LLVM version: 23.1.1' in version,version
        print('Warming prebuilt dependencies for',self.mode,flush=True)
        for label,edit in [('warm','original'),('changed','changed'),('original','original')]:
            result,_=self.invoke('parent-'+label,'parent',edit,'native')
            if label!='warm':
                assert result['dirty']==[self.unit]
                self.oracle[edit]=result
        for label,edit in [('warm','original'),('changed','changed'),('original','original')]:
            result,_=self.invoke('counter-parent-'+label,'parent',edit,'parent')
            self.assert_oracle(edit,result,label)
            if label!='warm':assert result['dirty']==[self.unit]
        assert shutil.disk_usage(self.state).free >= (self.budget+native.FLOOR_GIB)*native.GIB
        subprocess.run(['cp','-a','--reflink=auto',self.active,self.store/'stack'],check=True)
        a=snapshot(self.active);b=snapshot(self.store/'stack')
        assert a==b
        native.save(self.out/'snapshot.json',a)
        for arm in NAMES:
            for edit in ['changed','original']:
                label=arm+'-native-after-snapshot-'+edit
                result,_=self.invoke(label,arm,edit,'native')
                assert result['dirty']==[self.unit]
                self.assert_oracle(edit,result,label)
        native.save(self.out/'outcome.json',{'status':'native-oracles-match','mode':self.mode,'style':self.style})
        print('Matched native outputs and taint-free identical snapshots',self.mode,a,flush=True)

    def audit(self):
        assert json.loads((self.out/'outcome.json').read_text())['status']=='native-oracles-match'
        self.load_oracles()
        seed=self.spec['seeds'][self.mode]
        rng=random.Random(seed);edits=['original','changed']*6;rng.shuffle(edits)
        plan=[{'block':b,'edit':e,'arms':rng.sample(NAMES,2)} for b,e in enumerate(edits)]
        with (self.out/'plan.json').open('x') as f:json.dump({'seed':seed,'plan':plan},f,indent=2)
        for arm in NAMES:
            for label,edit,count in [('warm','original','parent'),('reset','changed','parent'),('probe','original','full')]:
                tag='audit-'+arm+'-'+label
                result,_=self.invoke(tag,arm,edit,count)
                self.assert_oracle(edit,result,tag)
                if label!='warm':assert result['dirty']==[self.unit],(tag,result['dirty'])
        native.save(self.out/'counter-audit.json',{'status':'four complete processes and correct rustc driver in both arms'})
        print('Both counter probes match their native outputs',self.mode,flush=True)

    def measure(self):
        assert (self.out/'counter-audit.json').exists()
        self.load_oracles()
        plan=json.loads((self.out/'plan.json').read_text())['plan']
        with (self.out/'observations.jsonl').open('x',buffering=1) as f:
            for block in plan:
                edit=block['edit'];other='original' if edit=='changed' else 'changed'
                for pos,arm in enumerate(block['arms']):
                    tag=f"{block['block']:02d}-{pos}"
                    reset,_=self.invoke(tag+'-reset',arm,other,'parent')
                    assert reset['dirty'] in [[],[self.unit]],(tag,reset['dirty'])
                    self.assert_oracle(other,reset,tag+'-reset')
                    result,counts=self.invoke(tag,arm,edit,'full')
                    assert result['dirty']==[self.unit],(tag,result['dirty'])
                    self.assert_oracle(edit,result,tag)
                    output_ids=sorted((key,val['sha256']) for key,val in result['outputs'].items())
                    digest=hashlib.sha256(json.dumps(output_ids,separators=(',',':')).encode()).hexdigest()
                    row=dict(block=block['block'],edit=edit,arm=arm,units=self.units,executables=self.exes,
                             source_sha256=hashlib.sha256(self.contents[edit]).hexdigest(),outputs_sha256=digest,
                             counts=counts,guest_ir=sum(counts.values()))
                    print(json.dumps(row),file=f)
                    print(self.mode,tag,arm,row['guest_ir'],flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['freeze','audit','measure'])
    ap.add_argument('style',choices=['full','prebuilt'])
    ap.add_argument('mode',choices=native.SELECTION)
    ap.add_argument('ruff',type=Path)
    ap.add_argument('spec',type=Path)
    ap.add_argument('state',type=Path)
    ap.add_argument('output',type=Path)
    args=ap.parse_args()
    study=Holdout(args)
    with (study.state.parent/(study.state.name+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:getattr(study,args.action)()
        finally:study.restore()


if __name__=='__main__':main()
