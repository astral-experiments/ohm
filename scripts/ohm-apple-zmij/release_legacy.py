"""Real unversioned signed rustc plus the shipped, previous receipt, and release-integrated Cargos."""
import json
import os
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import fixed_crc
import provider_edges as edges
from execs import ExecTrace
from study import TRIPLE, check_host, env_for, load, physical, run, save, sha
from versioned import CAGES,HARD,V1,V2,marker_rules
from versioned_named import case
from versioned_select import CARGOS,choose

# Signed -20's original register-only optimizer barrier already emits v1.
BARRIER='''#[inline(never)]
pub fn barrier(value: i32) -> i32 {
    let mut register = value as usize;
    unsafe { core::arch::asm!("/* {0} */", inout(reg) register, options(nomem,nostack,preserves_flags)); }
    register as i32
}
'''
def legacy(root):
    check_host(root,12);original=load(root/"receipts/release.json")
    sdk=root/"legacy-native";run(["/bin/cp","-cR",root/"signed",sdk],timeout=900)
    driver,=(sdk/"lib").glob("librustc_driver*.dylib")
    expected=original["driver"]["sha256"]
    assert sha(driver)==expected and sha(sdk/"bin/rustc")==original["rustc"]["sha256"]
    assert {f.name:sha(f) for f in (sdk/"lib/rustlib"/TRIPLE/"lib").iterdir() if f.is_file()}==original["std"]
    env=env_for(root/"legacy-proof",sdk);assert Path(run(["rustc","+ohm","--print","sysroot"],env=env).decode().strip()).samefile(sdk)
    assert run(["rustc","+ohm","-vV"],env=env).decode()==original["rustc_version"]
    p=root/"receipts/versioned/legacy";p.mkdir(parents=True)
    save(p/"producer.json",{"source":'7e71d3150938ff8ed82aca03416439d7e5b87ef3',"driver":physical(driver),"rustc":physical(sdk/"bin/rustc"),"fixture":BARRIER,"std":original["std"]})
    matrix=root/"receipts/provider-matrix";ar={v:(matrix/f"provider-{v}.a").read_bytes() for v in (17,29)}
    trace=ExecTrace();trace.ready();all_native={};all_named={}
    try:
        for name in ("signed","classic","aware"):
            bound=choose(root,name)
            src=root/"native/bin/cargo";temp=sdk/"bin/cargo.release.next";os.link(src,temp);os.replace(temp,sdk/"bin/cargo")
            assert (sdk/"bin/cargo").samefile(src) and sha(src)==bound["binary"]["sha256"]
            assert "commit-hash: "+CARGOS[name][0] in run(["cargo","+ohm","-Vv"],env=env).decode()
            all_named[name]={mode:case(root,trace,name,mode,legacy_sdk=sdk,barrier=BARRIER) for mode in CAGES}
            each={};all_native[name]=each
            for place in ("direct","library"):
                for watch in ("declared","unwatched"):
                    label="release-v1-"+name
                    rows=edges.run_case(root,trace,"legacy",place,watch,True,ar,label=label,evidence=fixed_crc.evidence,
                                        sdk_override=sdk,barrier=BARRIER)
                    origin=matrix/(label+"-"+place+"-"+watch+"-default")
                    phases={}
                    for phase,state,rust in edges.STEPS:
                        row=rows[phase]
                        want=[101,None] if edges.NATIVE[state] is None else [0,[edges.NATIVE[state],rust]]
                        assert row["empty"][:2]==want
                        # Cargo-declared directories and actual Rust edits must always be sound.
                        if watch=="declared" or phase not in edges.NO_RUST:
                            assert row["warm"][:2]==want and row["same_checked_image"] is not False,(name,place,watch,phase,row)
                        for arm in ("warm","empty"):
                            phase_row=load(origin/phase/arm/"verified.json")
                            if phase_row["status"]==0:
                                raw=marker_rules(root,phase_row)
                                assert raw and all(v==[V1] for _,v in raw),(name,place,watch,phase,arm,raw)
                        phases[phase]={"warm":row["warm"][:2],"empty":want,"same":row["same_checked_image"]}
                    dest=p/name/(place+"-"+watch);dest.parent.mkdir(parents=True,exist_ok=True);origin.rename(dest)
                    each[place+"-"+watch]=phases
    finally:trace.close()
    # The two released-v1 policy paths should make the same native decisions. Record any
    # discrepancy before enforcing it, including all old unwatched missing-file responses.
    delta=[]
    for kind in all_native["signed"]:
        for step,s in all_native["signed"][kind].items():
            n=all_native["aware"][kind][step]
            if n["warm"]!=s["warm"]:delta.append([kind,step,s,n])
    save(p/"terminal.json",{"rows":all_native,"signed_integrated_differences":delta,"named":all_named,
        "native_commands":len(CARGOS)*2*2*len(edges.STEPS)*2,"literal_commands":len(CARGOS)*len(CAGES)*3})
    assert not delta,delta
    choose(root,"aware")
if __name__=="__main__":legacy(Path(sys.argv[1]).resolve())
