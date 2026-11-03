"""Bind the final, affected LLD invocation to an emitted script and retain unmodified earlier links."""
from pathlib import Path
import json
import os
import shlex
import gate as g
import policy

def check(w,installed,inventory,evidence=None):
    out=evidence if evidence is not None else w/"trait-evidence/driver-witness";cap=g.read(out/"capture.json")
    assert cap["arm"]=="T" and cap["exit"]==0
    stage_root=w/"source/rust/build"/g.POLICY["target"]
    target_bin=Path("lib/rustlib")/g.POLICY["target"]/"bin"
    wrapped=target_bin/"gcc-ld/ld.lld";real=target_bin/"rust-lld"
    installed_files={}; aliases=[wrapped.parent/n for n in ("ld.lld","ld64.lld","lld-link","wasm-ld")]
    assert {Path(n) for n in inventory if Path(n).parent==wrapped.parent}==set(aliases)
    for path in (*aliases,real):
        item=inventory[path.as_posix()]
        assert item["sha256"]==g.sha(installed/path) and item["bytes"]==(installed/path).stat().st_size
        installed_files[path.as_posix()]=item
    final_name=Path(cap["pre_bolt"]["live"]).name
    full=[]
    for k,q in cap["links"].items():
        raw=policy.untar(q["argv"],out)
        assert raw.endswith(b"\x00") and q["argv_sha256"]==q["argv"]["sha256"]
        argv=list(map(os.fsdecode,raw[:-1].split(b"\x00")))
        assert argv.count("-flavor")==1 and argv[argv.index("-flavor")+1]=="gnu"
        assert argv.count("-o")==1 and Path(argv[argv.index("-o")+1]).name==Path(q["output"]).name
        outer=q["outer_cc"];chain=outer["chain_lld_to_cc"]
        assert len(chain)>=2 and len(set(chain))==len(chain) and (chain[0],chain[-1])==(q["pid"],outer["pid"])
        ccraw=policy.untar(outer["argv"],out);assert ccraw.endswith(b"\0")
        ccargs=list(map(os.fsdecode,ccraw[:-1].split(b"\0")));base=Path(outer["cwd"])
        responses={p["path"]:policy.untar(p,out) for p in outer["responses"]}
        assert set(responses)=={str(base/a[1:]) for a in ccargs if a.startswith("@")}
        expanded=[]
        for a in ccargs:
            if a.startswith("@"):expanded.extend(shlex.split(os.fsdecode(responses[str(base/a[1:])])))
            else:expanded.append(a)
        ldr={p["path"]:policy.untar(p,out) for p in outer["linker_responses"]}
        assert set(ldr)=={str(base/a[5:]) for a in ccargs if a.startswith("-Wl,@")}
        assert expanded.count("-o")==1 and (base/expanded[expanded.index("-o")+1]).resolve()==Path(q["output"])
        assert not any("-Bsymbolic-non-weak-functions" in s or "--export-dynamic-symbol-list=" in s for s in expanded+list(map(os.fsdecode,ldr.values())))
        exe=Path(q["exe"])
        stage=exe.relative_to(stage_root).parts[0]
        assert exe==stage_root/stage/real
        wrapper=q["gnu_wrapper"];assert Path(wrapper["path"])==stage_root/stage/wrapped
        assert Path(wrapper["resolved"]).is_relative_to(w/"source/rust/build")
        assert policy.untar(wrapper,out).startswith(b"\x7fELF")
        exact_flags=[a for a in argv if a.startswith(("--version-script=","--export-dynamic-symbol-list=","-Bsymbolic"))]
        assert exact_flags==q["options"]
        scripts={f["path"]:f for f in q["scripts"]}
        assert exact_flags and set(scripts)=={a.split("=",1)[1] for a in exact_flags if "=" in a}
        for sc in scripts.values():policy.untar(sc,out)
        full.append((stage,argv,q,scripts))
    selected=[s for s in full if Path(s[2]["output"]).name==final_name]
    (stage,argv,q,scripts),=selected
    assert stage=="stage1" and q["exe_sha256"]==inventory[real.as_posix()]["sha256"]
    assert argv.count("-Bsymbolic-non-weak-functions")==1
    policy_args=[s for s in argv if s.startswith("--export-dynamic-symbol-list=")]
    arg,=policy_args
    file=arg.split("=",1)[1]
    rec=cap["policies"][file]
    assert scripts[file]["sha256"]==rec["exceptions"]["sha256"] and policy.untar(scripts[file],out)==policy.untar(rec["exceptions"],out)
    assert len(policy.exports(policy.untar(rec["exceptions"],out)))>1500
    origins=json.loads(policy.untar(rec["supplier_evidence"],out))["receipts"]
    actual=q["actual_rlibs"];raw_paths=[a for a in argv if a.endswith(".rlib")]
    assert len(actual)==len(raw_paths) and actual
    matched=[];protected=[]
    for arg,rlib in zip(raw_paths,actual):
        assert Path(arg).name==Path(rlib["path"]).name
        k=f"{rlib['dev']:x}-{rlib['ino']:x}"
        if k in origins:
            origin=origins[k];assert (origin["bytes"],origin["mtime_ns"])==(rlib["bytes"],rlib["mtime_ns"])
            matched.append(rlib|{"origin_receipt":k,"cargo_manifest":origin["observed_native_sources"][0]["manifest"]})
        else:protected.append(rlib)
    assert matched and protected
    previous=[s for s in full if s[2] is not q]
    assert {"stage0-sysroot","stage1"}<={s[0] for s in previous}
    assert all(not any(a.startswith(("-Bsymbolic","--export-dynamic-symbol-list=")) for a in a0) for _,a0,_,_ in previous)
    return {"stage_executables":{str(r["pid"]):{"stage":st,"output":r["output"],"actual_rust_lld":r["exe"],"lld_sha256":r["exe_sha256"],"gnu_wrapper":r["gnu_wrapper"],"outer_cc":r["outer_cc"],"argv":r["argv"],"policy_flags":[a for a in a0 if a.startswith(("-Bsymbolic","--export-dynamic-symbol-list="))]} for st,a0,r,_ in full},
            "installed_files":installed_files,"producing_rustc_pid":int(Path(file).stem),"final_lld_pid":q["pid"],"final_output":q["output"],"owner_record":rec["owners"],"closed_exceptions":rec["exceptions"],"prior_unmodified_driver_links":len(previous),
            "final_link_input_rlibs":{"physically_matched_compiler_inputs":matched,"without_an_observed_compiler_artifact_link":protected}}
