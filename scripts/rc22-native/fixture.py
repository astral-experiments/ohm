"""Ruff-locked native-dependency fixture and in-place native provider transitions."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *

LIB='rc22_native_choice'
APP='rc22_probe'
BAD='let _: u16 = "rc22 semantic error";'
INITIAL='let _: u16 = 7;'
STEPS=[('lower','low',17),('appearance','high29',29),('same-stat','high41',41),
       ('malformed','bad',None),('repair','high29',29),('removal','low',17),
       ('missing','absent',None),('restore','low',17),('rust-error','source-invalid',None),('rust-repair','low',17)]

def project(src,kind,upstream):
    """Project the original locked package records, without choosing newer transitive dependencies."""
    name=kind;version,checksum=LOCKED[name];src.mkdir();(src/'src').mkdir()
    dep='zmij::Buffer::new().format(1.25_f64)=="1.25"' if kind=='zmij' else 'std::mem::size_of::<Option<objc2::rc::Retained<objc2::runtime::AnyObject>>>()==std::mem::size_of::<usize>()'
    src.joinpath('Cargo.toml').write_text(f'[workspace]\n[package]\nname="{APP}"\nversion="0.1.0"\nedition="2024"\n[dependencies]\n{name}="={version}"\n')
    src.joinpath('src/main.rs').write_text(f'#[link(name="{LIB}",kind="static",modifiers="-bundle")]\nunsafe extern "C" {{ fn qa_rc22_value() -> i32; fn qa_rc22_origin() -> *const std::ffi::c_char; }}\nfn main() {{ {INITIAL} assert!({dep}); println!("{{}} {{}}", unsafe {{ qa_rc22_value() }}, unsafe {{ std::ffi::CStr::from_ptr(qa_rc22_origin()) }}.to_str().unwrap()); }}\n')
    src.joinpath('build.rs').write_text('fn main() {\n let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("native");\n for d in ["early","late"] {println!("cargo:rustc-link-search=native={}",root.join(d).display());}\n println!("cargo:rerun-if-changed=build.rs");\n}\n')
    locked=tomllib.loads(upstream.read_text())['package'];deps=[(name,version)]
    if kind=='objc2':deps.append(('objc2-encode','4.1.0'))
    chosen=[q for q in locked if (q['name'],q['version']) in deps]
    require(len(chosen)==len(deps),'Ruff lock lacks registry sample')
    records=[*chosen,{'name':APP,'version':'0.1.0','dependencies':[name]}]
    lock='version = 4\n'
    for item in sorted(records,key=lambda q:q['name']):
        lock+='\n[[package]]\n'
        for key in ('name','version','source','checksum','dependencies'):
            if key in item:lock+=f'{key} = '+json.dumps(item[key])+'\n'
    src.joinpath('Cargo.lock').write_text(lock)
    main,=[q for q in chosen if q['name']==kind]
    require(main['checksum']==checksum and main['source']=='registry+https://github.com/rust-lang/crates.io-index','unmatched Ruff package')
    if kind=='objc2':require(main['dependencies']==['objc2-encode'],'foreign objc2 dependency graph')
    return {f:sha(src/f) for f in ('Cargo.toml','src/main.rs','build.rs','Cargo.lock')}

def provider_archive(body, object_name, object_body, apple):
    """Bind the only object and its order independently of how the platform ar lists its index."""
    require(body.startswith(b'!<arch>\n'), 'wrong archive magic')
    pos=8; members=[]
    while pos<len(body):
        header=body[pos:pos+60]
        require(len(header)==60 and header[58:]==b'`\n', 'broken native member header')
        size=int(header[48:58]);start=pos+60;end=start+size
        require(0<size and end<=len(body), 'native member size')
        name=header[:16].rstrip(b' ');payload=body[start:end]
        if name.startswith(b'#1/'):
            n=int(name[3:])
            require(0<n<len(payload), 'broken BSD extended member')
            name=payload[:n].rstrip(b'\x00');payload=payload[n:]
        elif name!=b'/':
            name=name.removesuffix(b'/')
        members.append((name.decode('ascii'),payload))
        pos=end+size%2
        require(pos<=len(body) and body[end:pos] in (b'',b'\n'), 'broken archive padding')
    expected=('__.SYMDEF','__.SYMDEF SORTED') if apple else ('/',)
    require(len(members)==2 and members[0][0] in expected and members[1][0]==object_name,
            ('unexpected native members',[k for k,_ in members]))
    require(members[1][1]==object_body, 'archived provider object differs')
    return [k for k,_ in members]

def providers(base,receipts):
    for name in ('early','late','source'):(base/name).mkdir(parents=True)
    wd=base/'source';src=wd/'member.c';obj=wd/'member.o'
    cc=Path(run(['/usr/bin/xcrun','-f','clang']) if host()==APPLE else shutil.which('cc')).resolve(strict=True)
    ar=Path(run(['/usr/bin/xcrun','-f','ar']) if host()==APPLE else shutil.which('ar')).resolve(strict=True)
    bodies={};proof={}
    for value in (17,29,41):
        text=f'int qa_rc22_value(void) {{ return {value}; }}\nconst char *qa_rc22_origin(void) {{ return "OHM_RC22_SELECTED_NATIVE_IMAGE_{value}"; }}\n';src.write_text(text)
        subprocess.run([cc,'-O2','-g0','-c',src,'-o',obj],check=True)
        output=wd/('role-'+str(value)+'.a')
        subprocess.run([ar,'crs',output,obj.name],cwd=wd,check=True,env={**os.environ,'ZERO_AR_DATE':'1'})
        body=output.read_bytes()
        members=provider_archive(body,obj.name,obj.read_bytes(),host()==APPLE)
        listing=run([ar,'t',output]).splitlines()
        for f in (obj,output):shutil.copy2(f,receipts/(str(value)+'-'+f.name))
        proof[str(value)]={'source':text,'archive_sha256':sha(output),'object_sha256':sha(obj),'bytes':len(body),'members':members,'ar_t':listing}
        bodies[value]=body
    require(len({len(b) for b in bodies.values()})==1 and len(set(bodies.values()))==3,'same-stat native challenge inadmissible')
    save(receipts/'providers.json',{'cc':ident(cc),'ar':ident(ar),'bodies':proof});return bodies

def configure(base,bodies,state):
    outputs={}
    for name in ('early','late'):
        f=base/name/('lib'+LIB+'.a')
        old=ident(f) if f.exists() else None
        data=None
        if name=='late' and state!='absent':data=bodies[17]
        if name=='early':data={'high29':bodies[29],'high41':bodies[41],'bad':b'NATIVE_BAD_ARCHIVE'+bytes(len(bodies[41])-18)}.get(state)
        if data is None:
            if f.exists():f.unlink()
        elif not f.exists():f.write_bytes(data)
        elif f.read_bytes()!=data:
            size=f.stat().st_size;ts=f.stat();require(len(data)==size,'replacement grew or shrank')
            with f.open('r+b',buffering=0) as h:h.write(data);os.fsync(h.fileno())
            os.utime(f,ns=(ts.st_atime_ns,ts.st_mtime_ns));now=ident(f)
            require(all(old[k]==now[k] for k in ('dev','ino','mtime_ns','bytes')) and old['sha256']!=now['sha256'],'same-stat replacement did not take')
        outputs[name]={'before':old,'after':ident(f) if f.exists() else None}
    return outputs
