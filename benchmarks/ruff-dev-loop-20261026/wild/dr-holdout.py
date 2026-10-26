#!/usr/bin/env python3
"""Audit and count the four native programs independently with DynamoRIO after a native warmup."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('hold',ROOT/'final-holdout.py');hold=importlib.util.module_from_spec(spec);spec.loader.exec_module(hold)
native=hold.native
DR=Path('/home/dev-user/.cache/ohm-dynamorio-20261026')
RUN=DR/'sdk/bin64/drrun'
CLIENT=DR/'client/libpidcounter.so'
NAMES=['cargo','rustc','clang','ld.bfd']


def bash_dispatch(name,path,extra=[]):
    args=' "$@"'+''.join(' '+shlex.quote(str(x)) for x in extra)
    native=shlex.quote(str(path))+args
    return ('#!/bin/sh\nif [ -n "${OHM_COUNT_OUT:-}" ]; then\n'
            +'  printf \'%s\\0\' '+native+' > "$OHM_COUNT_OUT/'+name+'.$$.argv"\n'
            +'  exec '+shlex.quote(str(RUN))+' -no_follow_children -c '+shlex.quote(str(CLIENT))+
            ' "$OHM_COUNT_OUT/'+name+'.$$.ir" -- '+native+'\nfi\nexec '+native+'\n')


def observe_maps(directory,stop,observed,programs):
    seen={}
    while not stop.is_set():
        for f in directory.glob('*.argv'):
            role=f.name.rsplit('.',2)[0];pid=f.name.rsplit('.',2)[1]
            if role not in programs:continue
            try:lines=Path('/proc',pid,'maps').read_text().splitlines()
            except (FileNotFoundError,ProcessLookupError):continue
            for line in lines:
                parts=line.split(None,5)
                if len(parts)!=6 or not parts[5].startswith('/'):continue
                name=parts[5]
                if name in [str(programs[role]),str(programs[role].resolve())]:
                    observed.setdefault(role,set()).add(name)
                if role=='rustc' and name.endswith('/'+Path(native.DRIVER).name):
                    observed.setdefault('driver',set()).add(name)
        stop.wait(.010)


def profiles(directory,selected,runtime,clang,wild):
    subjects={name:str(p.resolve()) for name,p in [('cargo',runtime/'bin/cargo'),('rustc',runtime/'bin/rustc'),('clang',clang),('ld.bfd',wild)]}
    counted={}
    traces={}
    for name in NAMES:
        ir,=directory.glob(name+'.*.ir');pid=ir.name.split('.')[1]
        args=(directory/(name+'.'+pid+'.argv')).read_bytes().split(b'\0')
        assert args[-1]==b'' and Path(os.fsdecode(args[0])).resolve()==Path(subjects[name]),(name,args[:3],subjects)
        if name=='rustc':
            assert b'--sysroot' in args and b'--crate-name' in args
        if name=='clang':assert b'-Wl,--no-fork' in args
        if name=='ld.bfd':assert b'--no-fork' in args or any(a.startswith(b'@') for a in args[1:])
        rows=[line.split() for line in ir.read_text().splitlines()]
        assert rows[0]==['B',pid,'0','0'] and rows[-1]==['P',pid,'0','0'],(name,rows[:2],rows[-2:])
        assert all(len(v)==4 and v[0] in ['B','T','F','P','S'] and v[1]==pid for v in rows)
        assert sum(v[0]=='B' for v in rows)==sum(v[0]=='P' for v in rows)==1
        registered=[v[2] for v in rows if v[0]=='T'];finished=[v[2] for v in rows if v[0]=='F']
        assert sorted(registered)==sorted(finished) and len(set(registered))==len(registered),(name,pid,registered,finished)
        counted[name]=sum(int(v[3]) for v in rows if v[0]=='F')
        assert counted[name]>0
        traces[name]={'pid':pid,'threads':len(registered),'driver':str(selected) if name=='rustc' else None}
    assert len(list(directory.glob('*.ir')))==len(list(directory.glob('*.argv')))==4
    native.save(directory/'processes.json',{'counts':counted,'traces':traces,'native_exec_roster':'audit-native-traces.json'})
    return counted


class Study(hold.Holdout):
    def enable(self):
        assert self.style=='prebuilt' and not self.active.exists() and (self.store/'parent').is_dir()
        self.out.mkdir()
        self.old=Path(str(self.out).removesuffix('-dr'))
        assert self.old!=self.out
        for e in self.contents:
            loc=self.out/('parent-'+e);loc.mkdir();shutil.copy2(self.old/('parent-'+e)/'result.json',loc/'result.json')
        shutil.copy2(self.old/'compiler-identities.json',self.out/'compiler-identities.json')
        self.load_oracles()
        shim=self.state/'dr-dispatch';(shim/'bin').mkdir(parents=True)
        for comp in (self.runtime/'bin').iterdir():
            if comp.name!='cargo':(shim/'bin'/comp.name).symlink_to(comp)
        (shim/'lib').symlink_to(self.runtime/'lib')
        cargo=shim/'bin/cargo';cargo.write_text(bash_dispatch('cargo',self.runtime/'bin/cargo'));cargo.chmod(0o755)
        entry=self.rustup/'toolchains/ohm';assert entry.resolve()==self.runtime.resolve()
        temp=entry.with_name('ohm.new');temp.symlink_to(shim);temp.replace(entry)
        linker=self.state/'wild-dispatch';linker.write_text(bash_dispatch('ld.bfd',self.linker));linker.chmod(0o755)
        self.clang.write_text(bash_dispatch('clang',Path(shutil.which('clang')),['--ld-path='+str(linker),'-Wl,--no-fork']))
        self.clang.chmod(0o755)
        native.save(self.out/'tool-digests.json',{str(p):native.sha(p) for p in [RUN,CLIENT,cargo,linker,self.clang,self.state/'compiler-wrapper']})
        # Keep report and physical artifacts of the rejected instrumented context. Exclude
        # that context from the subsequent snapshot rather than altering any fingerprints.
        gather=lambda d:{m[1] for line in (self.old/d/'stdout.jsonl').read_text().splitlines() if
                         (m:=re.search(r'/(v2-[0-9a-f]{16}-all-native-all)/',line))}
        good=gather('parent-warm');bad=gather('counter-parent-warm')-good
        assert len(good)==len(bad)==1,(good,bad)
        original=self.store/'parent';quarantine=self.state/'rejected-cachegrind-context'
        moved=[]
        for key in bad:
            for path in sorted(original.rglob(key)):
                assert path.is_dir()
                dest=quarantine/path.relative_to(original);dest.parent.mkdir(parents=True,exist_ok=True)
                path.rename(dest);moved.append(str(path.relative_to(original)))
        native.save(self.out/'rejected-cachegrind.json',{'native':sorted(good),'counter':sorted(bad),'quarantined':moved})
        for e in ['changed','original']:
            r,_=self.invoke('verify-original-native-'+e,'parent',e,'native')
            self.assert_oracle(e,r,e);assert r['dirty']==[self.unit]
        allocated=int(subprocess.check_output(['du','-s','--block-size=1',str(self.active)],text=True).split()[0])
        native.save(self.out/'snapshot-space.json',{'source_allocated_bytes':allocated,'floor_gib':native.FLOOR_GIB,
                                                    'free_before_clone':shutil.disk_usage(self.state).free})
        assert shutil.disk_usage(self.state).free >= allocated+(native.FLOOR_GIB+1)*native.GIB
        subprocess.run(['cp','-a','--reflink=auto',self.active,self.store/'stack'],check=True)
        a=hold.snapshot(self.active);b=hold.snapshot(self.store/'stack');assert a==b
        native.save(self.out/'snapshot.json',a)
        for arm in ['parent','stack']:
            for e in ['changed','original']:
                label=arm+'-native-after-snapshot-'+e
                r,_=self.invoke(label,arm,e,'native')
                assert r['dirty']==[self.unit],(label,r['dirty'])
                self.assert_oracle(e,r,label)
        native.save(self.out/'outcome.json',{'status':'native-oracles-match','mode':self.mode,'style':'prebuilt-dynamorio'})
        print('Independent frozen native oracles match',self.mode,flush=True)

    def audit2(self):
        self.load_oracles()
        order=__import__('random').Random(self.spec['seeds'][self.mode])
        edits=['original','changed']*6;order.shuffle(edits)
        plan=[{'block':i,'edit':e,'arms':order.sample(hold.NAMES,2)} for i,e in enumerate(edits)]
        expected={'seed':self.spec['seeds'][self.mode],'plan':plan}
        pp=self.out/'plan.json'
        if pp.exists():assert json.loads(pp.read_text())==expected
        else:native.save(pp,expected)
        traces={}
        for arm in hold.NAMES:
            for i,(edit,method) in enumerate([('original','native'),('changed','native-trace'),('original','full')]):
                label='clean-audit-'+arm+'-'+str(i)
                r,_=self.invoke(label,arm,edit,method)
                self.assert_oracle(edit,r,label)
                if i:assert r['dirty']==[self.unit],(label,r['dirty'])
                if method=='native-trace':
                    paths=[]
                    for line in (self.out/label/'execs').read_text().splitlines():
                        m=re.match(r'^\s*(\d+)\s+execve\("([^"]+)".*\)\s+=\s+0$',line)
                        if m:paths.append([m[1],str(Path(m[2]).resolve())])
                    for p in [self.state/'compiler-wrapper',self.runtime/'bin/rustc',self.clang,self.state/'wild-dispatch',self.linker,Path(shutil.which('clang'))]:
                        assert sum(x[1]==str(p.resolve()) for x in paths)==1,(label,p,paths)
                    traces[arm]=paths
        native.save(self.out/'audit-native-traces.json',traces)
        native.save(self.out/'counter-audit.json',{'status':'both native exec rosters, four complete independent counters, all mapped programs and selected rustc drivers verified'})
        print('Native and instrumented process audits match',self.mode,flush=True)

    def invoke(self,label,arm,edit,count):
        self.move(arm)
        seen=self.source.read_bytes();assert seen in self.contents.values()
        if seen!=self.contents[edit]:self.source.write_bytes(self.contents[edit])
        local=dict(self.env);directory=self.out/label
        args=[]
        stop=threading.Event();observed={};watch=None
        programs={'cargo':self.runtime/'bin/cargo','rustc':self.runtime/'bin/rustc','ld.bfd':self.linker,'clang':Path(shutil.which('clang'))}
        if count=='full':
            local['OHM_COUNT_OUT']=str(directory)
            watch=threading.Thread(target=observe_maps,args=(directory,stop,observed,programs),daemon=True);watch.start()
        elif count=='native-trace':
            args=['strace','-f','-qq','-e','trace=execve','-s','350','-o',str(directory/'execs')]
        inputs={'cargo':self.runtime/'bin/cargo','wild':self.linker};before=native.identities(inputs)
        try:r=native.capture(self.repo,local,self.command,directory,self.state,prefix=args)
        finally:
            stop.set()
            if watch:watch.join()
        native.check_compilers(self.out,arm,self.runtime,self.selected_driver(arm))
        assert before==native.identities(inputs) and len(r['graph'])==self.units and len(r['outputs'])==self.exes
        if count=='full':
            selected=self.selected_driver(arm).resolve()
            native.save(directory/'observed-maps.json',{k:sorted(v) for k,v in observed.items()})
            assert {Path(x).resolve() for x in observed.get('driver',())}=={selected},(label,observed,selected)
            for role,path in programs.items():
                assert {Path(x).resolve() for x in observed.get(role,())}=={path.resolve()},(label,role,observed)
            counts=profiles(directory,selected,self.runtime,Path(shutil.which('clang')),self.linker)
        else:counts={}
        return r,counts

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['enable','audit','audit2','measure']);ap.add_argument('mode',choices=['build','test'])
    for a in ['ruff','spec','state','output']:ap.add_argument(a,type=Path)
    args=ap.parse_args();args.style='prebuilt';s=Study(args)
    with (s.state.parent/(s.state.name+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:getattr(s,args.action)()
        finally:s.restore()
