from pathlib import Path
import hashlib, json, os, re, subprocess as sp, tempfile
H=Path(__file__).resolve().parent
import sys
sdk=Path(sys.argv[1]).resolve()
rustc=sdk/'bin/rustc';triple='x86_64-unknown-linux-gnu'
sha=lambda data:hashlib.sha256(data).hexdigest()
def run(args,**kw):
    return sp.run(args,check=True,stdout=sp.PIPE,stderr=sp.PIPE,**kw).stdout
def test():
    assert sha(rustc.read_bytes())==sys.argv[3]
    lld,=sdk.rglob('rust-lld')
    env=dict(PATH='/usr/bin:/bin',LC_ALL='C',RUSTC_BOOTSTRAP='1')
    observed={}
    def compile_role(out,extra,more=None):
        args=[rustc,'--crate-name','rustc_driver','--crate-type','dylib','--target',triple,'-Cprefer-dynamic=yes','-Copt-level=1','--emit=link','-Clink-arg=-Wl,-q','--print=link-args',*extra,'-o',out,H/'rust-policy.rs']
        p=sp.run(args,env={**env,**(more or {})},stdout=sp.PIPE,stderr=sp.PIPE)
        if p.returncode:raise RuntimeError(p.stderr.decode())
        return (p.stdout+p.stderr).decode()
    def syms(out):
        return {r[-1]:r[-2] for line in run(['nm','-D','--defined-only',out]).decode().splitlines() if len(r:=line.split())==3}
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp)
        base_dir=t/'base';base_dir.mkdir()
        base=base_dir/'libpolicy.so'
        log=compile_role(base,[])
        assert '-fuse-ld=lld' in log,log[:400]
        snapshot=syms(base)
        def name(needle):
            xs=[s for s in snapshot if needle in s and (needle!="weak_hook" or snapshot[s]=="W")]
            assert len(xs)==1,(needle,xs)
            return xs[0]
        work=name('rust_work');weak=name('weak_hook');strong=name('strong_hook')
        body=name('explicit_body');spoof=name('spoof_10hook_name')
        assert [(s,snapshot[s]) for s in [work,weak,strong,body,spoof]]==[(work,'T'),(weak,'W'),(strong,'T'),(body,'T'),(spoof,'T')]
        pre=t/'preserve.list'
        kept=sorted(snapshot.keys()-{work})
        assert all(re.fullmatch('[A-Za-z0-9_.$]+',s) for s in kept)
        pre.write_text('{\n'+''.join('  '+s+';\n' for s in kept)+'};\n')
        preserve_sha=sha(pre.read_bytes())
        def linker_args(path):
            return ['-Clink-arg=-Wl,-Bsymbolic-non-weak-functions','-Clink-arg=-Xlinker','-Clink-arg=--export-dynamic-symbol-list='+str(path)]
        switch=linker_args(pre)
        treated_dir=t/'candidate';treated_dir.mkdir();treated=treated_dir/'libpolicy.so'
        applied=compile_role(treated,switch)
        assert all(x in applied for x in ('-Bsymbolic-non-weak-functions','--export-dynamic-symbol-list='+str(pre),'-fuse-ld=lld'))
        assert syms(treated)==snapshot
        refs=[work,weak,strong,body,spoof]
        shim=t/'override.c'
        shim.write_text(''.join('unsigned long r%d(unsigned long) asm("%s");\nunsigned long r%d(unsigned long x){return x+%d;}\n'%(i,s,i,101+i) for i,s in enumerate(refs)))
        preloaded=t/'shim.so';run(['cc','-shared','-fPIC',shim,'-o',preloaded])
        cli=t/'cli.c'
        cli.write_text('#include <stdio.h>\nextern unsigned long get_slot(unsigned long,unsigned long);\nextern unsigned long outside(unsigned long) asm("'+work+'");\nint main(){for(int i=0;i<4;i++)printf("%lu ",get_slot(i,10));printf("%lu\\n",outside(10));}\n')
        binary=t/'use';libdir=sdk/'lib/rustlib'/triple/'lib'
        run(['cc',cli,'-L'+str(base_dir),'-Wl,-rpath-link,'+str(libdir),'-l:libpolicy.so','-o',binary])
        dep=run(['readelf','-d',binary]).decode()
        assert 'libpolicy.so' in dep
        for label,d in [('original',base_dir),('policy',treated_dir)]:
            local={**env,'LD_LIBRARY_PATH':os.pathsep.join(map(str,[d,libdir,sdk/'lib']))}
            normal=run([binary],env=local).decode().split()
            live=run([binary],env={**local,'LD_PRELOAD':str(preloaded)}).decode().split()
            assert normal=='11 12 13 14 11'.split()
            assert live==('111 112 113 115 111' if label=='original' else '11 112 113 115 111').split(),(label,live)
            rel=run(['readelf','-rW',d/'libpolicy.so']).decode()
            flags=run(['readelf','-dW',d/'libpolicy.so']).decode()
            dynamic=rel.split("Relocation section '.rela.plt'")[0].split("Relocation section '.rela.text'")[0]
            row={s:len(re.findall(r'^[0-9a-f]+\s+\S+\s+R_X86_64_\S+\s+[0-9a-f]+\s+'+re.escape(s)+r'\s+\+',dynamic,re.M)) for s in [work,weak,strong,spoof]}
            assert (row[work]>0)==(label=='original') and all(row[s]>0 for s in [weak,strong,spoof]),row
            observed[label]=dict(baseline=list(map(int,normal)),interposed=list(map(int,live)),dynamic_relocations=row,elf_sha256=sha((d/'libpolicy.so').read_bytes()),dynsym=sha('\n'.join(sorted(syms(d/'libpolicy.so'))).encode()),linker_flags=[fl for fl in ['-fuse-ld=lld','-Bsymbolic-non-weak-functions','--export-dynamic-symbol-list='] if fl in (log if label=='original' else applied)])
        # Exercise the installed compiler's actual typed export traversal as well.
        auto=t/'auto';auto.mkdir();policy_dir=t/'automatic policy';policy_dir.mkdir()
        (policy_dir/'owners').write_text('rustc_driver\n')
        actual=compile_role(auto/'libpolicy.so',[],{'OHM_RUSTC_DRIVER_LINK_DIR':str(policy_dir)})
        assert syms(auto/'libpolicy.so')==snapshot
        ld=dict(env,LD_LIBRARY_PATH=os.pathsep.join(map(str,[auto,libdir,sdk/'lib'])))
        clean=list(map(int,run([binary],env=ld).split()))
        replaced=list(map(int,run([binary],env=ld|{'LD_PRELOAD':str(preloaded)}).split()))
        typed=sys.argv[4]=='T';assert sys.argv[4] in ('R','T')
        assert clean==[11,12,13,14,11] and replaced==([11,112,113,115,111] if typed else [111,112,113,115,111])
        lists=list(policy_dir.glob('*.exports'))
        assert len(lists)==int(typed) and ('-Bsymbolic-non-weak-functions' in actual)==typed
        if typed:
            names={l.strip().removesuffix(';') for l in lists[0].read_text().splitlines()}
            assert work not in names and {weak,strong,spoof}<=names
        observed['integrated']={'normal':clean,'interposed':replaced,'typed_policy':typed,'exception_sha256':sha(lists[0].read_bytes()) if typed else None}
        relocated=t/'path with space,comma';relocated.mkdir()
        second_list=relocated/'second.list';second_list.write_bytes(pre.read_bytes())
        equivalent_dir=t/'equivalent';equivalent_dir.mkdir();equivalent=equivalent_dir/'libpolicy.so'
        compile_role(equivalent,linker_args(second_list))
        assert equivalent.read_bytes()==treated.read_bytes(),'temporary filename affected output'
        omitted=set([strong,spoof])
        second_list.write_text('{\n'+''.join('  '+s+';\n' for s in kept if s not in omitted)+'};\n')
        altered_dir=t/'omitted';altered_dir.mkdir()
        compile_role(altered_dir/'libpolicy.so',linker_args(second_list))
        altered=run([binary],env={**env,'LD_LIBRARY_PATH':os.pathsep.join(map(str,[altered_dir,libdir,sdk/'lib'])),'LD_PRELOAD':str(preloaded)}).decode().split()
        assert altered=='11 112 13 14 111'.split(),altered
        # Missing input fails the native link; syntactically valid omission is
        # visible only to a typed manifest or a meaningful preload control.
        pre.unlink()
        p=sp.run([rustc,'--crate-name','rustc_driver','--crate-type','dylib','--target',triple,'-Cprefer-dynamic=yes',*switch,'-o',t/'refused.so',H/'rust-policy.rs'],env=env,stdout=sp.PIPE,stderr=sp.PIPE)
        assert p.returncode and b'preserve.list' in p.stderr and not (t/'refused.so').exists()
    spec=json.loads(run([rustc,'-Zunstable-options','--target',triple,'--print=target-spec-json'],env=env))
    d=dict(rustc=sha(rustc.read_bytes()),lld=sha(lld.read_bytes()),target_linker=spec['linker-flavor'],source_sha256=sha((H/'rust-policy.rs').read_bytes()),exports={s:snapshot[s] for s in refs},count=len(snapshot),preserved_names_sha=preserve_sha,observed=observed,missing_file_refused=True,comma_space_path_byte_identical=True,removed_strong_and_c_hook=list(map(int,altered)),scope='The actual installed Rust compiler and GNU LLD. This auxiliary EII fixture supplies its independent known exception names explicitly.')
    Path(sys.argv[2]).write_text(json.dumps(d,sort_keys=True,indent=1)+'\n');print({k:v['interposed'] for k,v in observed.items()})
if __name__=='__main__':test()
