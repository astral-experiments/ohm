"""Check internal interposition and actual linker ownership on an installed Linux SDK."""
import argparse, ast, hashlib, json, os, re, shutil, subprocess
from pathlib import Path

def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def save(path, obj): path.write_text(json.dumps(obj, sort_keys=True, indent=2)+'\n')
def run(argv, cwd, env):
    return subprocess.run(list(map(str,argv)),cwd=cwd,env=env,capture_output=True)
def output(argv,cwd,env):
    p=run(argv,cwd,env); assert p.returncode==0,(argv,p.stderr[-800:]); return p.stdout.decode()

def events(path):
    rows=[]
    for line in path.read_text().splitlines():
        if not line.rstrip().endswith('= 0') or 'execve(' not in line: continue
        m=re.search(r'execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:0x[^,)]*|/\*.*?\*/|NULL)',line)
        assert m, line[:300]
        rows.append((ast.literal_eval(m[1]),ast.literal_eval(m[2])))
    return rows

def check(sdk, source, dest, prior, old_cc, no_kernel):
    dest.mkdir(); rust=sdk/'bin/rustc'; env={**os.environ,'RUSTC_BOOTSTRAP':'1','LD_LIBRARY_PATH':str(sdk/'lib')}
    for key in ('LD_PRELOAD','OHM_RUSTC_DRIVER_LINK_DIR','OHM_RUSTC_DRIVER_LINK_EXPORTS'):env.pop(key,None)
    result={'mode':'original' if prior else 'repaired','banner':output([rust,'-vV'],dest,env),
            'rustc_sha256':sha(rust),'fixture_sha256':sha(source),'cases':{}}
    sign='-Bsymbolic-non-weak-functions'; pref='--export-dynamic-symbol-list='
    csrc=dest/'checker.c'
    csrc.write_text('#include <dlfcn.h>\n#include <stdio.h>\n#include <stddef.h>\ntypedef size_t (*f)(void);\nint main(int ac,char**av){void*so=dlopen(av[1],RTLD_NOW|RTLD_LOCAL); if(!so){fprintf(stderr,"%s",dlerror());return 2;} f*a=dlsym(so,"COMPILER_SLOT"),*b=dlsym(so,"HOOK_SLOT"); if(!a||!b)return 3;printf("%zu %zu\\n",(*a)(),(*b)());}\n')
    package=dest/'canonical-driver';(package/'src').mkdir(parents=True)
    root=package/'src/lib.rs';shutil.copyfile(source,root);assert sha(root)==sha(source)
    output(['cc',csrc,'-o',dest/'check','-ldl'],dest,env)
    shim=dest/'old-cc'
    shim.write_text('#!/bin/sh\nfor arg; do if [ "$arg" = "-fuse-ld=lld" ]; then echo "cc: error: unrecognized command line option -fuse-ld=lld" >&2; exit 1; fi; done\nexec /usr/bin/cc -fuse-ld=bfd "$@"\n')
    shim.chmod(0o755)
    batch=['untreated','normal','emit','replay','bfd','bfd-user','fallback','fallback-user']
    if old_cc: batch+=['genuine-old-cc','genuine-old-cc-user']
    for label in batch:
        work=dest/label;work.mkdir()
        policy=work/'scoped, policy';policy.mkdir();(policy/'owners').write_text('rustc_driver\n')
        (policy/'driver').write_text(str(package))
        more={**env, 'CARGO_MANIFEST_DIR':str(package)}
        if label!='untreated':more['OHM_RUSTC_DRIVER_LINK_DIR']=str(policy)
        out=work/'driver.so'
        cmd=[rust,root,'--crate-name','rustc_driver','--crate-type=dylib','--edition=2024','-Csymbol-mangling-version=v0','-Zunstable-options','-Clink-self-contained=+linker','-Clinker-features=+lld','-o',out]
        if label=='emit':
            (work/'objects').mkdir();cmd+=['-Zemit-rlink','-Ztemps-dir='+str(work/'objects')]
        elif label=='replay':
            recipe=dest/'emit/driver.rlink';assert recipe.is_file(),list((dest/'emit').glob('*.rlink'))
            first_image=dest/'emit/driver.so';temp=dest/'emit/first.so';first_image.rename(temp)
            cmd=[rust,recipe,'-Zlink-only'];out=first_image
        elif label.startswith('bfd'):
            cmd+=['-Clink-arg=-fuse-ld=bfd']
        elif label.startswith('fallback'):
            cmd+=['-Clinker='+str(shim)]
        elif label.startswith('genuine-old-cc'):
            cmd+=['-Clinker='+str(old_cc)]
        if label.endswith('-user'):cmd+=['-Clink-arg=-Wl,-Bsymbolic-functions']
        if not no_kernel:
            cmd=['strace','-f','-qq','-s','65535','-e','trace=execve','-o',work/'exec.trace',*cmd]
        cp=run(cmd,work,more);(work/'stderr').write_bytes(cp.stderr)
        calls=events(work/'exec.trace') if not no_kernel else []
        raw={'exit':cp.returncode,'argv':list(map(str,cmd)),'stderr':sha(work/'stderr'),
             'kernel':None if no_kernel else sha(work/'exec.trace')}
        if not no_kernel:
            workers=[(exe,args) for exe,args in calls if Path(exe).name in ['ld','ld.bfd','ld.lld','rust-lld','old-cc','gcc-4.8','gcc-5','gcc-7','gcc-13','cc','collect2']]
            save(work/'linkers.json',workers);raw['linkers']=sha(work/'linkers.json')
        result['cases'][label]=raw;save(dest/'progress.json',result)
        incompatible=label.startswith(('bfd','fallback','genuine-old-cc'))
        if prior and incompatible:
            assert cp.returncode!=0 and sign.encode() in cp.stderr and (b'unrecognized option' in cp.stderr or b'unknown argument' in cp.stderr),(label,cp.stderr[-1300:]); continue
        assert cp.returncode==0,(label,cp.stderr[-1800:])
        symtab=output(['nm','-D','--defined-only',out],work,env)
        selected,=[line.split()[-1] for line in symtab.splitlines() if line.split()[-1].startswith('_R') and line.split()[-1].endswith('compiler_value')]
        if label=='untreated':
            ov=dest/'override.c';ov.write_text('#include <stddef.h>\nsize_t f(void) __asm__("'+selected+'");\nsize_t f(void){return 21;}\nsize_t exported_hook(void){return 22;}\n')
            output(['cc','-fPIC','-shared',ov,'-o',dest/'override.so'],work,env)
        assert output([dest/'check',out],work,env)=='11 12\n'
        pre=output([dest/'check',out],work,dict(env,LD_PRELOAD=str(dest/'override.so'))).strip()
        local=label=='normal' or (prior and label=='emit') or label.endswith('-user')
        assert pre==('11 12' if label.endswith('-user') else '11 22' if local else '21 22'),(label,pre,local)
        data=output(['readelf','-Wr',out],work,env)
        assert any(selected in line for line in data.splitlines())== (not local),(label,'relocation')
        assert any(re.search(r'\bexported_hook\b',l) for l in data.splitlines())==(not label.endswith('-user')),(label,'hook relocation')
        if not no_kernel:
            if incompatible:
                physical=[(e,a) for e,a in calls if Path(e).name in ('ld','ld.bfd')]
                assert physical and not any(sign in a or any(v.startswith(pref) for v in a) for _,a in physical),(label,'foreign options')
                if label.endswith('-user'):assert any('-Bsymbolic-functions' in a for _,a in physical)
                if label.startswith(('fallback','genuine-old-cc')):
                    actual=shim if label.startswith('fallback') else old_cc
                    passes=[args for exe,args in calls if Path(exe)==actual]
                    assert len(passes)==2 and '-fuse-ld=lld' in passes[0] and '-fuse-ld=lld' not in passes[1],(label,passes)
            if not prior:
                llds=[a for e,a in calls if Path(e).name=='rust-lld']
                if label=='normal':
                    assert len(llds)==1 and llds[0][1:4]==['-flavor','gnu',sign] and llds[0][4].startswith(pref) and ', policy/' in llds[0][4],(label,llds)
                    path=Path(llds[0][4][len(pref):]);rows=[x.strip().removesuffix(';') for x in path.read_text().splitlines()]
                    assert selected not in rows and 'exported_hook' in rows
                else:assert not any(sign in a or any(v.startswith(pref) for v in a) for a in llds),(label,'unexpected policy')
        raw.update(elf=sha(out),internal_preload=pre,protected_hook=not label.endswith('-user'),retained_driver_relocation=not local,selected=selected)
        save(dest/'progress.json',result)
    save(dest/'accepted.json',result)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('sdk',type=Path);p.add_argument('source',type=Path);p.add_argument('new_output',type=Path);p.add_argument('--prior',action='store_true');p.add_argument('--old-cc',type=Path);p.add_argument('--no-kernel',action='store_true');a=p.parse_args()
    check(a.sdk.resolve(),a.source.resolve(),a.new_output.resolve(),a.prior,a.old_cc.absolute() if a.old_cc else None,a.no_kernel)
