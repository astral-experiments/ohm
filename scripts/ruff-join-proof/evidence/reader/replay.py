"""Reopen actual Cargo dep-info against mixed consumed-input compilers, including an in-place upgrade."""
import argparse, hashlib, io, json, os, re, shutil, signal, struct, subprocess, tempfile, time
from pathlib import Path

OLD = bytes([17, 255, 134, 93])
NEW = bytes([29, 255, 134, 93])
OLD_SUM = "3d06fa58de09f94b91c882b16d4b5780253ff7ab9c81c16e2be8e07765acfb4f"
NEW_SUM = "6aa7f054373fd0f38007db4bdba694355734d9854505ead597ee77f5e1658266"
BASE_CARGO = "5c053ef9e38322558eac8e0f82056b4e2e958d42ccee477c30c18ad16aa6af7a"
DRIVERS = {"c1": "d377ef6f819ac8dc5d200cc1ad435f76b00290e5bd2dfb83873b3e2f79d6a72c",
           "c2": "401860d7243a9af2e02d9d51fa6f0565c3352de4962eae163023daf65ecb5599"}
SAVE = """
extern crate proc_macro;
use proc_macro::TokenStream;
#[proc_macro]
pub fn save(_: TokenStream) -> TokenStream {
    let root = std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    if root.join("armed").exists() {
        let path = root.join("src/payload.bin");
        let file = std::fs::File::options().write(true).open(&path).unwrap();
        let timestamp = file.metadata().unwrap().modified().unwrap();
        std::fs::write(&path, [29, 255, 134, 93]).unwrap();
        file.set_modified(timestamp).unwrap();
    }
    "0".parse().unwrap()
}
"""
MAIN = """const USED: &[u8] = include_bytes!("payload.bin");
const _: [(); 17] = [(); USED[0] as usize];
const _: usize = saver::save!();
const ALSO: &[u8] = include_bytes!("./payload.bin");
const _: [(); SECOND] = [(); ALSO[0] as usize];
fn main() { println!("{} {}", USED[0], ALSO[0]); }
"""

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def available():
    return int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))) * 1024

def charge():
    assert available() >= 8 * 2**30 + 75 * 2**20 and shutil.disk_usage(args.root.parent).free >= 15 * 2**30

def seed(work,consistent=False):
    work.mkdir(); (work/'src').mkdir(); (work/'saver/src').mkdir(parents=True)
    (work/'Cargo.toml').write_text('[package]\nname="consumed-input"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nsaver={path="saver"}\n[workspace]\n')
    (work/'saver/Cargo.toml').write_text('[package]\nname="saver"\nversion="0.1.0"\nedition="2021"\n[lib]\nproc-macro=true\n')
    (work/'saver/src/lib.rs').write_text(SAVE)
    (work/'src/main.rs').write_text(MAIN.replace('SECOND','17' if consistent else '29'))
    (work/'src/payload.bin').write_bytes(OLD)
    if not consistent: (work/'armed').touch()

def install(role,cargo,expected,first):
    kit = args.root / ('sdk-'+role)
    driver, = (getattr(args,role)/'lib').glob('librustc_driver-*.so')
    assert sha(driver) == DRIVERS[role] and sha(cargo)==expected
    if first:
        (kit/'bin').mkdir(parents=True)
        for tool in ('rustc','rustdoc'): os.link(getattr(args,role)/'bin'/tool,kit/'bin'/tool)
        (kit/'lib').symlink_to(getattr(args,role)/'lib',True)
        ru=args.root/('rustup-'+role)/'toolchains';ru.mkdir(parents=True);(ru/'ohm').symlink_to(kit,True)
    incoming=kit/'bin/cargo.incoming';os.link(cargo,incoming);incoming.replace(kit/'bin/cargo')
    assert sha(kit/'bin/cargo')==expected

def encoded(path):
    b=io.BytesIO(path.read_bytes())
    def get(n):
        v=b.read(n);assert len(v)==n;return v
    def number(n):return int.from_bytes(get(n),'little')
    def data():
        n=number(4);assert n<=10**6;return get(n).decode()
    assert get(5)==bytes.fromhex('01000000ff')
    v=number(1); assert v in (2,4,5)
    rows=[]
    for _ in range(number(4)):
        tag=number(1);assert tag in (0,1);name=data();has=number(1);assert has in (0,1)
        rows.append([tag,name,([number(8),data()] if has else None)])
    assert number(4)==0 and not b.read()
    return v,rows

def snapshot(work, matching=None):
    raws=[p for p in (work/'target').rglob('*.d') if b'src/payload.bin' in p.read_bytes() and b'src/main.rs:' in p.read_bytes()]
    disks=list((work/'target').rglob('dep-bin-consumed-input'))
    if matching:
        raws=[p for p in raws if str(p)==matching['raw_path']]
        disks=[p for p in disks if str(p)==matching['fp_path']]
    raw,=raws;disk,=disks
    (work/'evidence').mkdir(exist_ok=True)
    for path in (raw,disk):
        body=work/'evidence'/sha(path)
        if not body.exists(): shutil.copyfile(path,body)
    checksum_lines=[line for line in raw.read_text().splitlines() if line.startswith('# checksum:') and line.endswith('payload.bin')]
    return {'raw_path':str(raw),'raw':sha(raw),'fp_path':str(disk),'fp':sha(disk),'raw_rows':checksum_lines,'encoded':encoded(disk)}

def run(work,role,phase,expected,owner,*,clean=False,mode='check'):
    charge();tree='-empty' if clean else ''; logs=work/'evidence';logs.mkdir(exist_ok=True)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LC_ALL','LANG','TZ')}
    kit=args.root/('sdk-'+role);env.update(RUSTUP_HOME=str(args.root/('rustup-'+role)),RUSTUP_TOOLCHAIN='ohm',RUSTC=str(kit/'bin/rustc'),CARGO_TARGET_DIR=str(work/('target'+tree)),CARGO_BUILD_BUILD_DIR=str(work/('build'+tree)),CARGO_HOME=str(work/'cargo-home'),CARGO_NET_OFFLINE='true')
    actual=subprocess.check_output(['rustup','which','--toolchain','ohm','cargo'],env=env,text=True).strip()
    assert Path(actual).samefile(kit/'bin/cargo')
    argv=['cargo','+ohm',mode,'--offline','--message-format=json','-vv']; path=work/'src/payload.bin';before=path.read_bytes();stamp=path.stat().st_mtime_ns
    trace=logs/(phase+'.exec'); out=logs/(phase+'.stdout'); err=logs/(phase+'.stderr')
    args2=['strace','-f','-qq','-s','200000','-e','trace=execve','-o',str(trace),'--',*argv]
    low=available()
    with out.open('wb') as a, err.open('wb') as b:
        p=subprocess.Popen(args2,cwd=work,env=env,stdout=a,stderr=b,start_new_session=True);start=time.monotonic()
        while p.poll() is None:
            low=min(low,available())
            if low<8*2**30 or time.monotonic()-start>100:
                os.killpg(p.pid,signal.SIGKILL);p.wait();raise RuntimeError(('resource guard',low,phase))
            time.sleep(.1)
    assert p.returncode==expected and path.stat().st_mtime_ns==stamp,(phase,p.returncode,err.read_text()[-950:])
    rows=[json.loads(x) for x in out.read_text().splitlines()]
    codes=[x['message']['code']['code']for x in rows if x.get('reason')=='compiler-message' and x['message'].get('code')]
    assert codes==(['E0308'] if expected else []) and rows[-1]=={'reason':'build-finished','success':expected==0},(phase,codes)
    processes=[s for s in trace.read_text().splitlines() if '"--crate-name", "consumed_input"' in s and ' = 0' in s and str(kit/'bin/rustc') in s]
    assert len(processes)==owner,(phase,expected,owner,len(processes),trace.read_text()[-2500:])
    fresh=[x['fresh'] for x in rows if x.get('reason')=='compiler-artifact' and x['target']['name']=='consumed-input']
    assert fresh == ([] if expected else [owner==0]),(phase,fresh)
    result={'phase':phase,'argv':argv,'cargo':sha(kit/'bin/cargo'),'rc':p.returncode,'errors':codes,'fresh':fresh,'physical_rustc':len(processes),'stdout':sha(out),'stderr':sha(err),'exec':sha(trace),'min_avail':low,'before':before.hex(),'after':path.read_bytes().hex(),'mtime_ns':stamp}
    if mode=='build':
        elf,=[Path(x['executable']) for x in rows if x.get('reason')=='compiler-artifact' and x['target']['name']=='consumed-input']
        result.update(elf_sha=sha(elf),verdict=subprocess.check_output([elf],text=True).strip()); assert result['verdict']=='29 29'
    (logs/(phase+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(work.name,phase,'rc',expected,'real owner',owner,flush=True)
    return result

def changed(work,role,epoch):
    seed(work);first=run(work,role,'during-save',0,1)
    assert first['before']==OLD.hex() and first['after']==NEW.hex(); (work/'armed').unlink()
    result=snapshot(work);version,rows=result['encoded'];assert version==epoch
    raw=result['raw_rows'];payload=[(n,s) for _,n,s in rows if n.endswith('payload.bin')]
    if role=='c1':
        assert [(line.split('=')[1].split(' ')[0],line.split(' ')[-1]) for line in raw]==[(OLD_SUM,'src/payload.bin'),(NEW_SUM,'src/./payload.bin')],raw
        if epoch==4: assert len(payload)==1 and payload[0][1]==[4,'blake3='+NEW_SUM],payload
        else: assert sorted(s[1] for _,s in payload)==sorted(['blake3='+OLD_SUM,'blake3='+NEW_SUM]),payload
    else: assert not raw and payload and all(s is None for _,s in payload),result
    (work/'evidence'/'after-save.json').write_text(json.dumps(result,indent=2)+'\n')

def repaired(work,role):
    source=work/'src/main.rs';s=source.read_text();assert s.count('[(); 17]')==1
    source.write_text(s.replace('[(); 17]','[(); 29]'))
    run(work,role,'repair',0,1);run(work,role,'repair-settled',0,0)
    a=run(work,role,'native-repair',0,1,mode='build');b=run(work,role,'native-empty',0,1,mode='build',clean=True)
    assert a['verdict']==b['verdict'] and a['elf_sha']==b['elf_sha']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','verify'])
    for n in ('root','old_cargo','c1','c2'):p.add_argument('--'+n.replace('_','-'),dest=n,type=Path,required=True)
    p.add_argument('--candidate',type=Path);p.add_argument('--sha');args=p.parse_args();charge()
    up=args.root/'upgrade'
    if args.stage=='prepare':
        args.root.mkdir();install('c1',args.old_cargo,BASE_CARGO,True)
        changed(up,'c1',4);run(up,'c1','poison-unchanged',0,0);run(up,'c1','poison-independent-empty',101,1,clean=True)
        print('poison bound',snapshot(up)['fp'],flush=True)
    else:
        assert args.candidate and args.sha and sha(args.candidate)==args.sha
        before=snapshot(up); saved=json.loads((up/'evidence/after-save.json').read_bytes())
        assert before['fp']==saved['fp'] and before['fp_path']==saved['fp_path']
        install('c1',args.candidate,args.sha,False)
        run(up,'c1','first-after-upgrade',101,1);repaired(up,'c1')
        end=snapshot(up,before);assert before['fp_path']==end['fp_path'] and end['encoded'][0]==5
        for role in ('c1','c2'):
            if role=='c2':install(role,args.candidate,args.sha,True)
            w=args.root/('fixed-'+role);changed(w,role,5)
            run(w,role,'first-unchanged',101,1);run(w,role,'independent-empty',101,1,clean=True);repaired(w,role)
            w=args.root/('positive-'+role);seed(w,True)
            run(w,role,'ordinary',0,1);run(w,role,'ordinary-unchanged',0,0)
        print('All exact older/current driver and upgrade controls passed.')
