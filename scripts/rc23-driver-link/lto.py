"""Join the compiler's physical input choices to the actual native inputs after cross-crate ThinLTO."""
import json
import os
from pathlib import Path
import re
import hashlib
import tomllib
import gate as g
import policy
from phase_config import phase
from lld_open import probe as opened_by_lld

def codegen_options(args):
    out=[]
    for i,key in enumerate(args):
        if key in ("-C","-Z"):out.append(key+args[i+1])
        elif key.startswith(("-C","-Z")):out.append(key)
    return out

def archive_stem(path):
    name=Path(path).name
    return name[3:-5] if re.fullmatch(r"lib[A-Za-z0-9_]+-[a-f0-9]{16}\.rlib",name) else None

def final_operands(out,q,argv,proof):
    raw=policy.untar(q["native_operands"],out);rows=json.loads(raw)
    assert [(r["index"],r["arg"]) for r in rows]==[(i,a) for i,a in enumerate(argv) if a.endswith((".o",".rlib"))]
    assert all(Path(r["arg"]).name==Path(r["path"]).name and r["bytes"]>0 and r["ino"]>0 and re.fullmatch(r"[a-f0-9]{64}",r["sha256"]) for r in rows)
    archives=[r for r in rows if r["arg"].endswith(".rlib")]
    assert [{k:r[k] for k in ("path","dev","ino","bytes","mtime_ns")} for r in archives]==q["actual_rlibs"]
    objects=[r for r in rows if r["arg"].endswith(".o")]
    # A module name is evidence of an instance surviving LTO. Source ownership
    # comes exclusively from the earlier physical archive and hard-link checks.
    def indexes(source):
        stem=archive_stem(source)
        return [r["index"] for r in objects if stem and stem in Path(r["path"]).name.split(".") and r["header"].startswith("7f454c46")]
    matched={k:indexes(r["used_source"]) for k,r in proof["qualified_matches"].items()}
    protected={r["key"]:indexes(r["source"]) for r in proof["proven_foreign"]}
    assert any(matched.values()) and any(protected.values()),("no object-level correspondence",matched,protected)
    return {"raw":q["native_operands"],"object_count":len(objects),"direct_rlib_count":len(archives),"owned_module_operand_indices":matched,"foreign_module_operand_indices":protected}

def verify(w,out,q,rec,argv,installed,expected):
    phaseout=out/"pre-lto";witness=out/"capture.json"
    early=phase.finish(phaseout,witness) if expected is None else phase.join(phaseout,witness,expected["foreign"])
    startup=g.read(phaseout/"start.json");config=g.read(phaseout/"cargo-config.json");closed=g.read(phaseout/"cargo-config-closed.json");cal=g.read(phaseout/"calibration.json")
    assert closed=={"config":config["sha256"],"absent":True} and hashlib.sha256(config["contents"].encode()).hexdigest()==config["sha256"]
    assert config["dev"]>0 and config["ino"]>0 and Path(config["path"])==w/"source/.cargo/config.toml"
    child=config["cargo_child_environment"]
    assert tomllib.loads(config["contents"])=={"env":child} and set(child)=={"RUSTC_WRAPPER_REAL","OHM_PHASE_OUT","OHM_PHASE_MANIFEST"}
    assert Path(child["OHM_PHASE_OUT"])==w/"trait-evidence/driver-witness/pre-lto" and child["OHM_PHASE_MANIFEST"]==startup["manifest"]==str(w/"source/rust/compiler/rustc_driver")
    assert Path(child["RUSTC_WRAPPER_REAL"]).parts[-4:]==("scripts","rc23-driver-link","prelto","phase-wrapper")
    assert set(startup["collector"])=={"phase.py","phase-wrapper","origins.py","read.py","observe.py"} and all(g.sha(g.HERE/"prelto"/name)==digest for name,digest in startup["collector"].items())
    assert cal["strace_sha256"]==startup["strace_sha256"]
    folder,=phaseout.glob("visit-*");request=g.read(folder/"request.json");actual=Path(request["argv"][0])
    assert request["manifest"]==startup["manifest"] and request["strace"]==startup["strace"]
    opts=codegen_options(request["argv"][1:])
    assert "-Clto=thin" in opts and any(o in ("-Zdylib-lto","-Zdylib-lto=yes") for o in opts) and not any(o in ("-Clinker-plugin-lto","-Clinker-plugin-lto=yes") for o in opts)
    src=w/"source/rust";root=src/"build"/g.POLICY["target"];stream=rec["cargo_message_stream"];cargo=stream["cargo"];reader=stream["json_reader"]
    assert stream["rustc_pid"]==early["target_pid"] and early["lld_pid"]==q["pid"] and early["closed_exception_sha256"]==rec["exceptions"]["sha256"]
    assert stream["chain"][0]["pid"]==stream["rustc_pid"] and stream["chain"][-1]["pid"]==reader["pid"]
    assert stream["rustc_launcher"]["sha256"]==request["rustc_sha256"] and policy.untar(stream["rustc_launcher"],out).startswith(b"\x7fELF")
    assert Path(stream["rustc_launcher"]["path"])==actual and str(actual)==startup["rustc"]
    assert cargo["stdout"]==reader["pipe"] and reader["fd"]>=0 and cargo["env"]["OHM_RUSTC_DRIVER_LINK_DIR"]==str(Path(early["policy"]).parent)
    cargov=[os.fsdecode(b) for b in policy.untar(cargo["argv"],out)[:-1].split(b"\0")]
    assert any(a.startswith(("--message-format=json-render-diagnostics","json-render-diagnostics")) for a in cargov)
    assert Path(cargo["cwd"])==src and actual.resolve()==Path(cargo["env"]["RUSTC_REAL"]).resolve()==(root/"stage1/bin/rustc").resolve() and cargo["env"]["RUSTC_STAGE"]=="1"
    assert all(re.fullmatch("[0-9a-f]{64}",x["exe_sha256"]) for x in (cargo,reader))
    if expected is None:
        assert Path(cargo["exe"]).resolve()==(root/"stage0/bin/cargo").resolve()
        assert Path(reader["exe"]).name=="bootstrap" and Path(reader["exe"]).is_relative_to(src/"build")
    else:
        assert (cargo["exe_sha256"],reader["exe_sha256"])==(expected["cargo"],expected["reader"])
    return {"early":early,"effective_codegen_options":opts,"physical_cargo_json_stream":stream,"kernel_lld_read":opened_by_lld(folder,q["pid"],q["exe"]),"after_lto":final_operands(out,q,argv,early),"observer_config_sha256":g.sha(phaseout/"cargo-config.json"),"observer_calibration_sha256":g.sha(phaseout/"calibration.json")}
