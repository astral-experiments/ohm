"""Exercise register comparisons through Cargo and retain the resulting native obligations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from capsule import need, save, sha

LIB = r'''
#[inline(never)]
pub fn equal(left: usize, right: usize) -> bool {
    let result: u8;
    unsafe {
        core::arch::asm!("cmp {left}, {right}", "sete cl", left=in(reg)left,
            right=in(reg)right, lateout("cl")result, options(nostack));
    }
    result != 0
}
'''
MAIN = 'fn main() { let v = std::env::args().nth(1).unwrap().parse().unwrap(); println!("{}", eq_probe::equal(v, 17)); }\n'

def exercise(work, env, role, label, expected, logs):
    argv = ["cargo","+ohm","build","--offline","--message-format=json"]
    p = subprocess.run(argv, cwd=work, env=env, capture_output=True)
    (logs/(role+"-"+label+".stdout")).write_bytes(p.stdout); (logs/(role+"-"+label+".stderr")).write_bytes(p.stderr)
    assert p.returncode==0,(role,label,p.stderr[-1700:])
    rows=[json.loads(line)for line in p.stdout.splitlines()]
    assert rows[-1]=={"reason":"build-finished","success":True}
    lib,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['kind']==['lib']]
    cli,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['kind']==['bin']]
    path,=[Path(n) for n in lib['filenames'] if Path(n).suffix=='.rmeta']
    dep=path.with_name(path.stem.removeprefix('lib')+'.d')
    data=dep.read_bytes();(logs/(role+"-"+label+".d")).write_bytes(data)
    untracked=b'/dev/null/ohm-untracked-relink-inputs:' in data.splitlines()
    need(untracked==(role in ('P','forced')),(role,label,"unexpected assembler dependency",data[-350:]))
    exe=Path(cli['executable']);values=[subprocess.check_output([exe,str(v)],env=env).decode().strip()for v in (12,17,18,999)]
    assert values==expected,(label,values)
    return dict(role=role,label=label,depinfo=sha(dep),elf=sha(exe),verdicts=values,library_fresh=lib["fresh"],bin_fresh=cli["fresh"],untracked=untracked)

def smoke(root, manifest, base):
    proxy=Path(shutil.which('rustup',path=base['PATH'])).resolve(strict=True);proxies=root/'proxies';proxies.mkdir()
    for name in ('cargo','rustc','rustdoc','rustup'):(proxies/name).symlink_to(proxy)
    alias=Path(base['RUSTUP_HOME'])/'toolchains/ohm';alias.parent.mkdir(parents=True,exist_ok=True)
    work=root/'real-compiler-case';(work/'src').mkdir(parents=True)
    (work/'Cargo.toml').write_text('[package]\nname="eq-probe"\nversion="0.1.0"\nedition="2021"\n[profile.dev]\ndebug=0\n[workspace]\n')
    (work/'src/lib.rs').write_text(LIB); all_rows=[]
    for role,label in (('P','normal'),('C','defer'),('forced','defer')):
        sdk=Path(manifest['arms'][label]['root']);need(sdk.samefile(root/'reopened'/label), 'foreign toolchain')
        if alias.is_symlink(): alias.unlink()
        alias.symlink_to(sdk,True)
        env=dict(base,PATH=str(proxies)+os.pathsep+base['PATH'],RUSTC=str(sdk/'bin/rustc'),RUSTUP_TOOLCHAIN='ohm',LD_LIBRARY_PATH=str(sdk/'lib'),CARGO_NET_OFFLINE='true',CARGO_HOME=str(root/(role+'-cargo-home')),CARGO_TARGET_DIR=str(root/(role+'-target')),CARGO_BUILD_BUILD_DIR=str(root/(role+'-shared')))
        env.pop('CARGO_INCREMENTAL',None)
        if role=='forced':env['OHM_QA_CONSERVATIVE_SETE']='1'
        for tool in ('rustc','cargo'):
            actual=subprocess.check_output(['rustup','which','--toolchain','ohm',tool],env=env,text=True).strip()
            assert Path(actual).samefile(sdk/'bin'/tool)
        (work/'src/main.rs').write_text(MAIN);old=['false','true','false','false'];new=['false','false','true','false']
        r=[exercise(work,env,role,'old',old,root/'logs'),exercise(work,env,role,'old-unchanged',old,root/'logs')]
        (work/'src/main.rs').write_text(MAIN.replace('v, 17','v, 18'))
        r+= [exercise(work,env,role,'real-edit',new,root/'logs'),exercise(work,env,role,'new-unchanged',new,root/'logs'),exercise(work,dict(env,CARGO_TARGET_DIR=str(root/(role+'-clean-target')),CARGO_BUILD_BUILD_DIR=str(root/(role+'-clean-shared'))),role,'independent-clean',new,root/'logs')]
        assert r[0]['elf']==r[1]['elf'] and r[2]['elf']==r[3]['elf']==r[4]['elf'] and r[0]['elf']!=r[2]['elf'],r
        all_rows+=r
    assert [r['elf'] for r in all_rows[:5]]==[r['elf']for r in all_rows[5:10]]==[r['elf']for r in all_rows[10:]],all_rows
    save(root/'logs/smoke.json',{'complete_native_histories':all_rows})
