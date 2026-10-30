"""Construct the source states and fingerprint the actual Apple or ELF executable."""
from __future__ import annotations
import gzip,hashlib,json,os,platform,re,shutil,struct,subprocess,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from packages import need,save,sha,platform_triple

CASES=[(owner,watch) for owner in ('direct','transitive') for watch in ('dir','file')]+[('direct','same-mtime'),('transitive','undeclared')]
# The source states are independent of role and are later replayed from empty stores.
STATES=[('cold','lower',7),('unchanged','lower',7),('changed-native','higher',7),('unchanged-higher','higher',7),('malformed','malformed',7),('repair-first','lower',7),('missing','missing',7),('repair-second','higher',7),('rust-edit','higher',11),('unchanged-rust-edit','higher',11),('invalid-rust','higher',None),('repair-rust','higher',13)]
PARITY=[('cold','lower',7),('unchanged','lower',7),('changed-native','higher',7),('unchanged-higher','higher',7),('rust-edit','higher',11),('unchanged-rust-edit','higher',11)]
ARCHIVE='libqa_release_boundary.a'
BARRIER='''
#[cfg(target_arch="aarch64")]
#[target_feature(enable="crc")]
#[inline(never)]
unsafe fn crc(mut v:u32,d:u32)->u32 { unsafe { core::arch::asm!("crc32w {v:w}, {v:w}, {d:w}",v=inout(reg) v,d=in(reg) d); } v }
#[inline(never)]
pub fn barrier(value:i32)->i32 {
    #[cfg(target_arch="aarch64")] unsafe {
        let mut vector:core::arch::aarch64::int32x4_t=core::mem::zeroed();
        core::arch::asm!("/*{:v}*/",inout(vreg) vector);
        core::hint::black_box(vector); assert_eq!(crc(0,0),0);
    }
    #[cfg(target_arch="x86_64")] unsafe {
        let mut s=core::hint::black_box(4.0_f64);
        core::arch::asm!("sqrtsd {s}, {s}",s=inout(xmm_reg) s,options(pure,nomem,nostack)); assert_eq!(s,2.0);
    }
    value
}
'''
NATIVE='''
#[link(name="qa_release_boundary",kind="static",modifiers="-bundle")]
unsafe extern "C" { fn qa_value()->i32; }
#[inline(never)] pub fn provider()->i32 { barrier(unsafe { qa_value() }) }
'''


def digest(x):return hashlib.sha256(x).hexdigest()
def compressed(p,body):
    p.parent.mkdir(parents=True,exist_ok=True)
    if not p.exists():
        with p.open('xb') as f:f.write(gzip.compress(body,compresslevel=2,mtime=0))
    return digest(body)
def source(p,body):
    if not p.exists() or p.read_text()!=body:p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
def environment(root,role):
    # A Cargo launched by CI should see exactly the ordinary developer settings.
    from shutil import which
    real=Path(which('rustup')).absolute();tool=root/('toolchain-'+role);aliases=tool/'toolchains';aliases.mkdir(parents=True,exist_ok=True);alias=aliases/'ohm';sdk=root/('sdk-'+role)
    if not alias.exists():alias.symlink_to(sdk.resolve(),target_is_directory=True)
    need(alias.samefile(sdk),'wrong physical SDK alias');cargo=root/'cargo-home';cargo.mkdir(exist_ok=True);home=root/'home';home.mkdir(exist_ok=True)
    env={k:os.environ[k] for k in ('USER','LOGNAME','SYSTEMROOT','TMPDIR','DEVELOPER_DIR','SDKROOT','LANG') if k in os.environ}
    env.update(HOME=str(home),PATH=os.pathsep.join([str(real.parent),'/usr/local/bin','/opt/homebrew/bin','/usr/bin','/bin','/usr/sbin','/sbin']),RUSTUP_HOME=str(tool),CARGO_HOME=str(cargo),CARGO_TARGET_DIR=str(root/'stores/target'),CARGO_BUILD_BUILD_DIR=str(root/'stores/shared'),CARGO_NET_OFFLINE='true',CARGO_CACHE_AUTO_CLEAN_FREQUENCY='never',CARGO_TERM_COLOR='never',LC_ALL='C',TZ='UTC')
    need(not ({'GITHUB_TOKEN','GH_TOKEN','CI','TF_BUILD','RUSTFLAGS','CARGO_INCREMENTAL'}&env.keys()),'contaminated developer environment');return env

def enroll_sdk(root,role,env):
    sdk=root/('sdk-'+role);out=root/'receipts'/role;facts={};prov=json.loads((out/'custody.json').read_bytes())['provenance']; t=platform_triple()
    for k,cmd in [('cargo',['cargo','+ohm','-Vv']),('rustc',['rustc','+ohm','-vV']),('sysroot',['rustc','+ohm','--print','sysroot']),('libdir',['rustc','+ohm','--print','target-libdir']),('cargo_path',['rustup','which','--toolchain','ohm','cargo']),('rustc_path',['rustup','which','--toolchain','ohm','rustc'])]:facts[k]=subprocess.check_output(cmd,env=env,text=True).strip()
    for n in ('rustc','cargo'):
        need(Path(facts[n+'_path']).samefile(sdk/'bin'/n) and prov['sources']['rust' if n=='rustc' else 'cargo']['revision'] in facts[n], 'unproved physical '+n+' sources')
    need(Path(facts['sysroot']).samefile(sdk) and Path(facts['libdir']).samefile(sdk/'lib/rustlib'/t/'lib'),'foreign target sysroot');save(out/'sdk.json',facts);save(out/'env.json',env)

def artifacts(root,env):
    d=root/'factory';d.mkdir(exist_ok=True);out=root/'receipts'/'factory'
    if (out/'originals.json').exists():return {v:(out/f'{v}.a').read_bytes() for v in (17,29)}
    out.mkdir(parents=True,exist_ok=True);mac=platform.system()=='Darwin';tool=lambda n:Path(subprocess.check_output(['xcrun','--find',n],env=env,text=True).strip()).resolve() if mac else Path(shutil.which(n,path=env['PATH'])).resolve();cc=tool('clang' if mac else 'cc');ar=tool('ar');q={};vals={}
    for value in (17,29):
        f=d/'provider.c';obj=d/'provider.o';a=d/f'{value}.a';source(f,f'__attribute__((noinline)) int qa_value(void) {{ return {value}; }}\n');cmds=[[str(cc),'-O1','-c',str(f),'-o',str(obj)],[str(ar),'rcs',str(a),str(obj)]]
        for cmd in cmds:subprocess.run(cmd,env=env|{'ZERO_AR_DATE':'1'},check=True,timeout=30)
        data=a.read_bytes();b=obj.read_bytes();need(data.startswith(b'!<arch>\n') and b[:4] in (b'\x7fELF',bytes.fromhex('cffaedfe')),'invalid native fixture');(out/f'{value}.a').write_bytes(data);(out/f'{value}.o').write_bytes(b);q[str(value)]={'source':f.read_text(),'archive':digest(data),'object':digest(b),'commands':cmds};vals[value]=data
    need(len(vals[17])==len(vals[29]) and vals[17]!=vals[29],'same-time control requires equal-sized distinct archives');save(out/'originals.json',{'tools':{str(p):sha(p) for p in (cc,ar)},'items':q});return vals

def form(root,owner,watch):
    cwd=root/'fixture';cwd.mkdir();pkg='[package]\nname="{}"\nversion="0.0.1"\nedition="2021"\nautobins=false\nautotests=false\n';manifest=pkg.format('qa_release_app')+'[workspace]\nresolver="2"\n[dependencies]\ntrigger={path="trigger"}\n';source(cwd/'trigger/Cargo.toml',pkg.format('trigger'));(cwd/'trigger/src').mkdir();data=cwd/'native';data.mkdir();[(data/k).mkdir() for k in ('early','late','single')];
    tip='println!("QA_RESULT={} {}",provider(),trigger::value());';
    if owner=='direct':
        crate=cwd;manifest+='[[bin]]\nname="qa_release_app"\npath="src/main.rs"\n';source(cwd/'src/main.rs',BARRIER+NATIVE+'fn main(){'+tip+'}\n')
    else:
        crate=cwd/'owned';source(crate/'Cargo.toml',pkg.format('owned'));source(crate/'src/lib.rs',BARRIER+NATIVE);manifest+='owned={path="owned"}\n[[test]]\nname="qa_release_test"\npath="tests/contract.rs"\n';source(cwd/'tests/contract.rs','use owned::provider;\n#[test] fn provider_contract(){'+tip+'assert!([17,29].contains(&provider()));}\n')
    source(cwd/'Cargo.toml',manifest);mode='single' if watch!='dir' else 'both';watches={'dir':['early','late'],'file':['single/'+ARCHIVE],'same-mtime':['single/'+ARCHIVE],'undeclared':[]}[watch]
    script='''use std::{fs::OpenOptions,io::Write,path::Path};\nfn main(){\n let d=Path::new(DIR);\n println!("cargo:rerun-if-changed=build.rs");\n let mut rec=OpenOptions::new().create(true).append(true).open(LOG).unwrap();writeln!(rec,"run").unwrap();\n'''.replace('DIR',json.dumps(str(data))).replace('LOG',json.dumps(str(root/'script-invocations')))
    for name in watches:script+=f'println!("cargo:rerun-if-changed={{}}",d.join({json.dumps(name)}).display());\n'
    for name in (['single'] if mode=='single' else ['early','late']):script+=f'println!("cargo:rustc-link-search=native={{}}",d.join({json.dumps(name)}).display());\n'
    source(crate/'build.rs',script+'}\n');return cwd

def native_state(cwd,watch,state,originals,*,preserve=False):
    d=cwd/'native';malformed=b'QA malformed native archive\n';goals={'early':None,'late':None,'single':None}
    if watch=='dir':
        if state!='missing':goals['late']=originals[17]
        if state=='higher':goals['early']=originals[29]
        if state=='malformed':goals['early']=malformed
    else:goals['single']={'lower':originals[17],'higher':originals[29],'malformed':malformed,'missing':None}[state]
    rows={}
    for k,v in goals.items():
        p=d/k/ARCHIVE;old=(p.stat() if p.exists() else None);parent=p.parent.stat();changed=(old is not None and v is None) or (v is not None and (old is None or p.read_bytes()!=v))
        if changed:
            if v is None:p.unlink()
            elif preserve:
                need(old is not None and len(v)==old.st_size,'not exact same timestamp case');p.write_bytes(v);os.utime(p,ns=(old.st_atime_ns,old.st_mtime_ns));need(p.stat().st_ino==old.st_ino and p.stat().st_mtime_ns==old.st_mtime_ns and p.parent.stat().st_mtime_ns==parent.st_mtime_ns,'failed same-inode, size and mtime control')
            else:
                temp=p.with_suffix('.tmp');temp.write_bytes(v);os.replace(temp,p)
        rows[k]={'bytes':len(v),'sha256':digest(v),'inode':p.stat().st_ino,'mtime_ns':p.stat().st_mtime_ns,'parent_mtime_ns':p.parent.stat().st_mtime_ns} if v is not None else None
    return rows

def source_state(cwd,value):source(cwd/'trigger/src/lib.rs','#[inline(never)] pub fn value()->i32 { '+('qa_missing_declared_symbol' if value is None else str(value))+' }\n')
def remove_owned(root,name):
    need(name in ('fixture','stores') and root.is_absolute() and (root/'receipts').is_dir(),'unowned temporary path');p=root/name
    if p.exists():need(p.is_dir() and not p.is_symlink() and p.parent==root,'foreign temporary directory');shutil.rmtree(p)

def cargo_messages(data):
    rows=[];build_lines=[]
    for line in data.splitlines():
        if line.startswith(b'{'):
            rows.append(json.loads(line));continue
        m=re.fullmatch(rb'\[(?:qa_release_app|owned) 0\.0\.1\] (cargo:(?:rerun-if-changed|rustc-link-search)=.+)',line)
        need(m is not None,'unexpected Cargo stdout framing: '+repr(line[:320]));build_lines.append(m[1].decode())
    need(rows and rows[-1].get('reason')=='build-finished','missing final typed record')
    return rows,build_lines

def allocated_sections(data):
    out={}
    if data[:4]==b'\x7fELF':
        need(data[4:6]==b'\x02\x01' and struct.unpack_from('<H',data,18)[0]==62,'not an x86_64 ELF');at=struct.unpack_from('<Q',data,40)[0];size,count,names=struct.unpack_from('<3H',data,58);need(size==64 and 0<names<count and at+count*size<=len(data),'invalid ELF sections');fmt='<IIQQQQIIQQ';r=[struct.unpack_from(fmt,data,at+i*size) for i in range(count)];table=data[r[names][4]:r[names][4]+r[names][5]]
        for name,kind,flags,addr,p,n,*_ in r:
            if not flags&2 or kind==8 or n==0:continue
            end=table.index(0,name);k=table[name:end].decode();need(p+n<=len(data) and k not in out,'invalid ELF allocated section');out[k]=[n,digest(data[p:p+n])]
        need('.text' in out and '.rodata' in out,'no ELF code/data')
    else:
        need(data[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',data,12)[0]==2,'not Apple ARM64 executable');count,sz=struct.unpack_from('<II',data,16);at=32
        for _ in range(count):
            cmd,n=struct.unpack_from('<II',data,at);need(n>=8 and at+n<=32+sz<=len(data),'bad Mach-O commands')
            if cmd==25:
                secs=struct.unpack_from('<I',data,at+64)[0];need(n==72+80*secs,'bad Mach-O section count')
                for j in range(secs):
                    sec=at+72+80*j;s,seg,addr,length,p=struct.unpack_from('<16s16sQQI',data,sec);flags=struct.unpack_from('<I',data,sec+64)[0];k=seg.rstrip(b'\0').decode()+','+s.rstrip(b'\0').decode()
                    if length and flags&255 not in (1,12,18):need(p>0 and p+length<=len(data) and k not in out,'invalid Mach-O section');out[k]=[length,digest(data[p:p+length])]
            at+=n
        need(at==32+sz and '__TEXT,__text' in out,'no Apple text')
    return out
