"""Cross-compile every checked-in GNU assembly case and run a real getpid syscall."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bootstrap import rt, CHILD, git

SRC='tests/run-make/ohm-checked-dep-info/gnu_aarch64.rs'
CFG='ordinary general_only vector_only scalar_modifier vector_modifier spaced input_only late discarded options separate compact_input compact_copy syscall syscall_file compact_constant compact_modifier compact_options compact_output compact_two_operands compact_file instruction file escape raw global'.split()
BEFORE={'ordinary','general_only','vector_only','compact_input','compact_copy'}
HARD='ohm-untracked-relink-inputs'; V2='/dev/null/ohm-recheck-dependent-links-v2:'
PROGRAM='''fn main() {
    let answer: usize;
    unsafe { core::arch::asm!("svc 0", in("x8") 172usize, lateout("x0") answer, options(nostack, preserves_flags)); }
    assert_eq!(answer, std::process::id() as usize);
    println!("same pid");
}
'''

def main():
    assert git(rt.ROOT/'rust','rev-parse','HEAD')==CHILD
    work=rt.ROOT/'direct';work.mkdir()
    source=rt.ROOT/'rust'/SRC
    shutil.copyfile(source,work/'case.rs')
    (work/'payload.bin').write_bytes(bytes(4));(work/'main.rs').write_text(PROGRAM)
    proxy=Path(shutil.which('rustup')).resolve(strict=True)
    shims=work/'shims';shims.mkdir()
    for name in ('rustc','rustup'):(shims/name).symlink_to(proxy)
    evidence={}
    for role,sdk in [('parent',Path(os.environ['CENSUS_PARENT'])),('candidate',rt.ROOT/'candidate-sdk')]:
        data=rt.LOG/('cross-'+role);data.mkdir()
        home=work/role;(home/'toolchains').mkdir(parents=True)
        (home/'toolchains/ohm').symlink_to(sdk,target_is_directory=True)
        env=dict(os.environ,RUSTUP_HOME=str(home),RUSTUP_AUTO_INSTALL='0',PATH=str(shims)+':'+os.environ['PATH'])
        rust=['rustc','+ohm','--target',rt.TARGET,'-Zohm-check-relink-inputs']
        dispatched=subprocess.check_output(['rustup','which','--toolchain','ohm','rustc'],cwd=work,env=env,text=True).strip()
        assert Path(dispatched).samefile(sdk/'bin/rustc')
        cases={}
        for cfg in CFG:
            p=subprocess.run([*rust,'--cfg',cfg,'--emit','link,dep-info=-','case.rs'],cwd=work,env=env,capture_output=True)
            (data/(cfg+'.stdout')).write_bytes(p.stdout);(data/(cfg+'.stderr')).write_bytes(p.stderr);p.check_returncode()
            rules=p.stdout.decode()
            accepted=cfg in BEFORE or (role=='candidate' and cfg=='syscall')
            assert (HARD in rules)==(not accepted) and (V2 in rules.splitlines())==accepted,(role,cfg,rules)
            assert '/dev/null/ohm-recheck-dependent-links:' not in rules.splitlines()
            cases[cfg]='checked-v2' if accepted else 'hard'
        exe=work/(role+'-getpid')
        p=subprocess.run([*rust,'-C','linker=/usr/bin/aarch64-linux-gnu-gcc','main.rs','-o',exe],cwd=work,env=env,capture_output=True)
        (data/'getpid-build.stderr').write_bytes(p.stderr);p.check_returncode()
        p=subprocess.run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',exe],capture_output=True,cwd=work,env=env)
        (data/'getpid.stdout').write_bytes(p.stdout);(data/'getpid.stderr').write_bytes(p.stderr);p.check_returncode()
        assert p.stdout==b'same pid\n'
        evidence[role]={'markers':cases,'getpid_elf':rt.sha(exe),'driver':rt.sha(next((sdk/'lib').glob('librustc_driver-*.so')))}
    assert [n for n in CFG if evidence['parent']['markers'][n]!=evidence['candidate']['markers'][n]]==['syscall']
    rt.save(rt.LOG/'cross-marker-and-getpid.json',evidence)

if __name__=='__main__':main()
