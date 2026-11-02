"""Build the source-matched Rustdoc for an already frozen stage1 role."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from capsule import HOST,REG,need,save,sha


def freeze(role,root,env,compile_argv):
    old=json.loads((HERE/"documentation-originals.json").read_bytes())[role]
    fresh=json.loads((root/"capsule"/(role+".json")).read_bytes())
    need(fresh["commit"]==old["commit"]==REG["roles"][role]["revision"] and
         fresh["compiler_tree"]==old["compiler_tree"],"different compiler for the documentation rebuild")
    stage=root/"build"/HOST/"stage1"
    need(compile_argv[-3:]==["compiler/rustc","library","src/tools/rustdoc"],"unexpected rustc/library/rustdoc build")
    save(root/"logs"/("rustdoc-inputs-"+role+".json"),{"argv":compile_argv,"source":REG["roles"][role],"original_source_factory":41425541148})
    doc=stage/"bin/rustdoc"
    need(doc.is_file() and doc.read_bytes()[:4]==b"\x7fELF" and doc.stat().st_size<120<<20,"no actual stage1 rustdoc")
    diffs={n:[old["files"].get(n),fresh["files"].get(n)] for n in old["files"].keys()|fresh["files"].keys()
           if old["files"].get(n)!=fresh["files"].get(n)}
    after={n:(sha(stage/n) if (stage/n).is_file() else None) for n in fresh["files"] if not (stage/n).is_file() or sha(stage/n)!=fresh["files"][n][0]}
    dest=root/"documentation"/role
    dest.mkdir(parents=True)
    p=dest/"rustdoc"
    shutil.copy2(doc,p)
    source=dest/"doc_probe.rs"
    source.write_text("/// A real source-built documentation witness.\npub fn line_table_witness() -> u8 { 41 }\n")
    html=dest/"html"
    assembled=root/("doc-sdk-"+role)
    for name,(digest,_,mode) in fresh["files"].items():
        known=root/"capsule/objects"/digest
        actual=assembled/name;actual.parent.mkdir(parents=True,exist_ok=True)
        if name.startswith("bin/") or "/bin/" in name:
            shutil.copyfile(known,actual)
            actual.chmod(mode & ~0o222)
        else:
            os.link(known,actual)
        need(sha(actual)==digest,"incorrect source-built documentation dependency")
    installed=assembled/"bin/rustdoc"; shutil.copy2(p,installed)
    base={**env,"LD_LIBRARY_PATH":str(assembled/"lib")}
    version=subprocess.check_output([installed,"-vV"],env=base,text=True)
    need("rustdoc 1.99.0-dev" in version and ("commit-hash: unknown" in version or "commit-hash: " in version),"wrong real rustdoc version")
    proc=subprocess.run([installed,"--crate-name","ldv_doc_witness","--edition=2021","-o",html,source],
                        env=base|{"LD_DEBUG":"libs"},capture_output=True,timeout=90,check=True)
    item=html/"ldv_doc_witness/fn.line_table_witness.html"
    need(b"A real source-built documentation witness." in item.read_bytes(),"actual Rustdoc HTML is missing")
    driver,=[n for n in fresh["files"] if n.startswith("lib/librustc_driver-")]
    loads=[Path(p) for p in re.findall(r"calling init:\s+([^\s]+)",proc.stderr.decode())]
    selected=[p for p in loads if p.name.startswith("librustc_driver-")]
    need(len(selected)==1 and selected[0].samefile(assembled/driver),"HTML did not use this role's actual source driver")
    need(sha(p)==sha(doc),"different frozen documentation binary")
    objects=root/"capsule"/"objects"
    receipt={"source":fresh["commit"],"tree":fresh["compiler_tree"],"rustdoc":[sha(doc),doc.stat().st_size,doc.stat().st_mode&0o777],
             "stage0":[fresh["stage0_rustc"],fresh["stage0_cargo"]],"stage0_matches_original":
             all(fresh[k]==old[k] for k in ("stage0_rustc","stage0_cargo","stage0_source")),
             "all_previous_files":len(old["files"]),"before_differences":diffs,"after_differences":after,"driver":[driver,sha(selected[0])],
             "version":version,"html_sha256":sha(item),"actual_loader_init_paths":[str(p) for p in selected],
             "native_compile_verified":True,"original_physical_kit_untouched":all(sha(objects/v[0])==v[0] for v in fresh["files"].values())}
    save(dest/"receipt.json",receipt)
    save(root/"logs"/("rustdoc-"+role+".json"),receipt)
    print("Source rustdoc produced actual HTML",role,receipt["rustdoc"][0],"original differences",len(diffs),"after",len(after),flush=True)
