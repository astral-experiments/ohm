#!/usr/bin/env python3
"""Count the real native Cargo process with DynamoRIO and the three descendant tool images with Cachegrind."""
import argparse,fcntl,hashlib,importlib.util,json,os,re,shlex,shutil,subprocess,threading
from pathlib import Path
src=Path(__file__).with_name('dr-holdout.py')
spec=importlib.util.spec_from_file_location('native_dr',src);dr=importlib.util.module_from_spec(spec);spec.loader.exec_module(dr)
n=dr.native


class Study(dr.Study):
    def setup_and_audit(self):
        assert not self.active.exists() and (self.out/'outcome.json').exists()
        archived=self.out/'unscored-dr-only';archived.mkdir()
        for item in list(self.out.glob('clean-audit-*'))+list(self.out.glob('audit-*-*')):
            if item.is_dir():item.rename(archived/item.name)
        wrapper=self.state/'compiler-wrapper';original=self.state/'audited-compiler-wrapper'
        assert n.sha(wrapper)==self.spec['wrapper']['sha256'] and not original.exists()
        shutil.copy2(wrapper,original)
        original_cmd=shlex.quote(str(original))
        wrapper.write_text('''#!/bin/sh
if [ -n "${OHM_HYBRID_OUT:-}" ]; then
  printf '%s\\0' "$@" > "$OHM_HYBRID_OUT/all-rustc.$$.argv"
  case " $* " in
    *" --crate-name ${OHM_PACKAGE:-} "*)
      unset OHM_COUNT_OUT
      exec valgrind --tool=cachegrind --cache-sim=no --branch-sim=no --trace-children=yes --verbose \\
        "--cachegrind-out-file=$OHM_HYBRID_OUT/guest.%p" "--log-file=$OHM_HYBRID_OUT/vg.%p" '''+original_cmd+''' "$@";;
  esac
fi
exec '''+original_cmd+''' "$@"
''');wrapper.chmod(0o755)
        n.save(self.out/'hybrid-tool-digests.json',{'audited_compiler_wrapper':n.sha(original),'outer_compiler_wrapper':n.sha(wrapper),
                'drrun':n.sha(dr.RUN),'pidcounter':n.sha(dr.CLIENT),'cachegrind':subprocess.check_output(['valgrind','--version'],text=True).strip()})
        self.audit2()
        for arm,rows in json.loads((self.out/'audit-native-traces.json').read_bytes()).items():
            assert sum(x[1]==str(original.resolve()) for x in rows)==1,(arm,rows)
        n.save(self.out/'counter-audit.json',{'status':'one complete DynamoRIO Cargo, three complete Cachegrind children, one selected driver, full native references'})

    def invoke(self,label,arm,edit,count):
        self.move(arm)
        data=self.source.read_bytes();assert data in self.contents.values()
        if data!=self.contents[edit]:self.source.write_bytes(self.contents[edit])
        directory=self.out/label;env=dict(self.env);args=[];stop=threading.Event();observed={};watch=None
        if count=='full':
            env.update(OHM_COUNT_OUT=str(directory),OHM_HYBRID_OUT=str(directory))
            roles={'cargo':self.runtime/'bin/cargo'}
            watch=threading.Thread(target=dr.observe_maps,args=(directory,stop,observed,roles),daemon=True);watch.start()
        elif count=='native-trace':
            args=['strace','-f','-qq','-e','trace=execve','-s','350','-o',str(directory/'execs')]
        inputs={'cargo':self.runtime/'bin/cargo','wild':self.linker};before=n.identities(inputs)
        try:r=n.capture(self.repo,env,self.command,directory,self.state,prefix=args)
        finally:
            stop.set()
            if watch:watch.join()
        n.check_compilers(self.out,arm,self.runtime,self.selected_driver(arm))
        assert before==n.identities(inputs) and (len(r['graph']),len(r['outputs']))==(self.units,self.exes)
        counts={}
        if count=='full':
            c,=directory.glob('*.ir');name,pid,ext=c.name.split('.');assert name=='cargo'
            rows=[x.split() for x in c.read_text().splitlines()]
            assert rows[0]==['B',pid,'0','0'] and rows[-1]==['P',pid,'0','0']
            a=[x[2] for x in rows if x[0]=='T'];b=[x[2] for x in rows if x[0]=='F']
            assert sorted(a)==sorted(b) and len(a)==len(set(a)),(a,b)
            assert all(len(x)==4 and x[1]==pid and x[0] in ['B','T','F','P','S'] for x in rows)
            assert sum(x[0]=='B' for x in rows)==sum(x[0]=='P' for x in rows)==1
            counts['cargo']=sum(int(x[3]) for x in rows if x[0]=='F');assert counts['cargo']>0
            assert {Path(x).resolve() for x in observed.get('cargo',())}=={(self.runtime/'bin/cargo').resolve()},observed
            cargofile,=directory.glob('cargo.*.argv');assert cargofile.name.split('.')[1]==pid
            assert Path(os.fsdecode(cargofile.read_bytes().split(b'\0')[0])).resolve()==(self.runtime/'bin/cargo').resolve()
            actual,=directory.glob('all-rustc.*.argv')
            argv=actual.read_bytes().split(b'\0');assert argv[argv.index(b'--crate-name')+1].decode()==self.unit
            profiles=list(directory.glob('guest.*'));assert len(profiles)==len(list(directory.glob('vg.*')))==3
            images={}
            for p in profiles:
                cmd=None;total=None
                with p.open() as fd:
                    for line in fd:
                        if line.startswith('cmd: '):cmd=line[5:].split()
                        elif line.startswith('summary: '):total=int(line.split()[1])
                assert cmd and total
                item=Path(cmd[0]).name;assert item not in counts
                log=(directory/f'vg{p.suffix}').read_text();assert log.count(' I refs:')==1 and 'Process terminating' not in log
                expected={'rustc':self.runtime/'bin/rustc','clang':Path(shutil.which('clang')),'ld.bfd':self.linker}
                assert Path(cmd[0]).resolve()==expected[item].resolve(),(item,cmd[0])
                if item=='rustc':
                    mapped={Path(line.split('Reading syms from ',1)[1].strip()).resolve() for line in log.splitlines()
                            if 'Reading syms from ' in line and line.rstrip().endswith('/'+Path(n.DRIVER).name)}
                    assert mapped=={self.selected_driver(arm).resolve()},(label,mapped)
                if item=='clang':assert '-Wl,--no-fork' in cmd
                if item=='ld.bfd':assert '--no-fork' in cmd or len(cmd)==2 and cmd[1].startswith('@')
                counts[item]=total;images[item]={'pid':int(p.suffix[1:]),'image':str(expected[item].resolve())}
            assert set(counts)==set(dr.NAMES)
            images['cargo']={'pid':int(pid),'image':str((self.runtime/'bin/cargo').resolve()),'threads':len(a)}
            n.save(directory/'processes.json',{'counts':counts,'images':images,'selected_driver':str(self.selected_driver(arm).resolve()),
                  'one_rustc_argv_sha256':n.sha(actual),'engines':{'cargo':'DynamoRIO','rustc':'Cachegrind','clang':'Cachegrind','ld.bfd':'Cachegrind'}})
        return r,counts

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['setup_and_audit','measure']);ap.add_argument('mode',choices=['build','test'])
    for a in ['ruff','spec','state','output']:ap.add_argument(a,type=Path)
    args=ap.parse_args();args.style='prebuilt';s=Study(args)
    with (s.state.parent/(s.state.name+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:getattr(s,args.action)()
        finally:s.restore()
