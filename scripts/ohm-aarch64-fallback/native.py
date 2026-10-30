"""Read actual GCC/ld/ELF behavior with changed native search, preserved inode/mtime and independent clean."""
from pathlib import Path
from hashlib import sha256 as H
import json,os,runpy,stat,subprocess,sys
HERE=Path(__file__).resolve().parent
HOLD=runpy.run_path(str(HERE.parent/'ohm-aarch64-confirm/study.py'))
from ruff import rt,q
from study import save,load,sha,need
import edges,edge_guard

# Both genuine locked-crate shapes in the same compiled body, enabled by the normal GNU target.
GNU='''
#[inline(never)] pub fn barrier(mut x:usize)->usize {
    let mut v:core::arch::aarch64::int32x4_t=unsafe { core::mem::zeroed() };
    unsafe {
        core::arch::asm!("/*{0}*/", inout(reg) x);
        core::arch::asm!("/*{:v}*/", inout(vreg) v);
        core::arch::asm!("/* {value} */", value=in(reg) x, options(nomem,nostack));
    }
    core::hint::black_box(v);x
}
'''
PAIRS=(('higher','empty-higher'),('removed-higher','empty-removed-higher'),
       ('same-inode-value','empty-same-inode-value'),('real-Rust-edit','empty-real-Rust-edit'),
       ('same-inode-malformed','empty-same-inode-malformed'),('repaired-edit','empty-repaired-edit'),
       ('missing','empty-missing'),('restored-edit','empty-restored-edit'),('restored-repeat','empty-restored-edit'))
def ident(p):
 s=p.stat(follow_symlinks=False);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
 return {'sha256':sha(p),'dev':s.st_dev,'ino':s.st_ino,'ctime_ns':s.st_ctime_ns,'mtime_ns':s.st_mtime_ns,
         'size':s.st_size,'mode':stat.S_IMODE(s.st_mode),'nlink':s.st_nlink}
def overwrite(path,data):
 before=ident(path);assert path.stat().st_size==len(data) and before['sha256']!=H(data).hexdigest()
 times=path.stat()
 with path.open('r+b',buffering=0) as f:
  assert f.write(data)==len(data);os.fsync(f.fileno())
 os.utime(path,ns=(times.st_atime_ns,times.st_mtime_ns));after=ident(path)
 assert all(before[k]==after[k] for k in ('dev','ino','size','mtime_ns','mode','nlink'))
 assert before['sha256']!=after['sha256']==H(data).hexdigest()
 return {'before':before,'after':after}
def mutations(root,cwd,early,late,initial,ar,version,visit):
 proofs={};rt.room()
 alternate=ar(29,early);assert len(initial)==len(alternate) and alternate!=initial
 proofs['distinct_native_archives']={'lower':ident(late),'higher':ident(early)}
 assert initial.startswith(b'!<arch>\n') and alternate.startswith(b'!<arch>\n')
 visit('higher');visit('empty-higher',True)
 early.unlink();visit('removed-higher');visit('empty-removed-higher',True)
 proofs['value']=overwrite(late,alternate)
 visit('same-inode-value');visit('empty-same-inode-value',True)
 version(11);visit('real-Rust-edit');visit('empty-real-Rust-edit',True)
 bad=b'!<arch>\n'+b'\0'*(len(initial)-8)
 proofs['malformed']=overwrite(late,bad)
 visit('same-inode-malformed');visit('empty-same-inode-malformed',True)
 proofs['repair']=overwrite(late,alternate)
 version(13);visit('repaired-edit');visit('empty-repaired-edit',True)
 late.unlink();visit('missing');visit('empty-missing',True)
 late.write_bytes(initial);version(19);visit('restored-edit');visit('empty-restored-edit',True);visit('restored-repeat')
 for b in (initial,alternate,bad):q.custody(b,'.a')
 save(root/'physical-provider-bytes.json',proofs)
def main(mode,ancestor,inputs,product):
 assert mode in ('signed','293')
 p=load(product/'product.json') if mode=='293' else None
 select,history=HOLD['setup'](ancestor,inputs,(product/'cargo',p) if p else None)
 edges.BARRIER=GNU;default=edges.BUILD;sets={};base_sha=rt.TOOLS['bin/cargo']
 for role in 'ANM':
  select(role);assert sha(rt.SDK/'bin/cargo')==(p['cargo_sha256'] if p else base_sha)
  version=rt.record(['cargo','+ohm','-Vv'],rt.LOG/('cargo-version-'+role),rt.ROOT,rt.environment())
  assert (p['git'] if p else rt.CARGO_SOURCE).encode() in version.stdout
  for watch in ('undeclared','directories','files'):
   decl={'files':'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");','directories':'println!("cargo:rerun-if-changed={n}");','undeclared':''}[watch]
   edges.BUILD=default.replace('for n in ["early","late"]{','for n in ["early","late"]{'+decl)
   for placement in ('direct','library'):
    label='-'.join((role,watch,placement));root=rt.LOG/label;root.mkdir()
    edges.run(root,role,placement,True,history=mutations,rust_source=HOLD['SOURCE'][role])
    j=load(root/'completed.json');ca={r['name']:r for r in j['cases']}
    assert len(ca)==len(j['cases'])==18
    assert j['defaults'] and j['source']==HOLD['SOURCE'][role] and j['placement']==placement
    assert ca['cold-lower']['answer']=='17 7' and len(ca['cold-lower']['selected'])>0
    mismatches=[]
    for name,ref in PAIRS:
     x,y=ca[name],ca[ref]
     expect={'higher':'29 7','removed-higher':'17 7','same-inode-value':'29 7','real-Rust-edit':'29 11',
             'same-inode-malformed':None,'repaired-edit':'29 13','missing':None,'restored-edit':'17 19','restored-repeat':'17 19'}[name]
     assert y['answer']==expect and y['exit']==(101 if expect is None else 0) and len(y['actual_GNU_linkers'])>=1
     if expect is not None:assert any(('/early/' if name=='higher' else '/late/') in l for l in y['selected'])
     if (x['exit'],x['answer'],x['elf'])!=(y['exit'],y['answer'],y['elf']):mismatches.append(name)
    sets[label]={'complete':sha(root/'completed.json'),'physical_mutations':sha(root/'physical-provider-bytes.json'),'relative_to_own_clean':mismatches}
    print(mode,label,'clean differences',mismatches,flush=True)
 save(rt.LOG/'native-group.json',{'cargo':mode,'cargo_sha':sha(rt.SDK/'bin/cargo'),'cargo_commit':p['git'] if p else rt.CARGO_SOURCE,
  'all':sets,'order':list(sets),'same_stamp':True,'real_mutations':True,'all_role_sources':HOLD['SOURCE'],'all_selections':history})
if __name__=='__main__':main(sys.argv[1],*map(Path,sys.argv[2:]))
