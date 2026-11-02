"""Install and exercise matched documentation tools without changing the two retained compilers."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import transport as t

DOC_SOURCE=b"/// Independently emitted documentation for the original compiler kit.\npub fn ldv_registry_identity() {}\n"


def qualification(role,row,original):
    driver,=[n for n in original["files"] if n.startswith("lib/librustc_driver-")]
    t.need(row["source"]==original["commit"]==t.capsule.REG["roles"][role]["revision"] and
           row["tree"]==original["compiler_tree"] and row["driver"]==[driver,original["files"][driver][0]] and
           row["all_previous_files"]==len(original["files"])==63 and not row["before_differences"] and
           not row["after_differences"] and row["original_physical_kit_untouched"] and row["native_compile_verified"] and
           row["stage0_matches_original"] and row["stage0"]==[original["stage0_rustc"],original["stage0_cargo"]] and
           re.fullmatch(r"[0-9a-f]{64}",row["html_sha256"]) and len(row["actual_loader_init_paths"])==1,
           "documentation was not built with the precise original role and runtime")
    key,size,mode=row["rustdoc"]
    t.need(re.fullmatch(r"[0-9a-f]{64}",key) and 0<size<120<<20 and mode&0o100 and mode&0o6000==0,
           "invalid source-built documentation file")
    return key,size


def install(root):
    spec=json.loads((t.HERE/"source-equivalence.json").read_bytes())["source_docs"]
    t.run_identity(spec["run"],spec["qa"])
    item=t.artifact(t.fetch(f"runs/{spec['run']}/artifacts?per_page=100")["artifacts"],"ohm-ldv-source-rustdoc")
    t.need([item["id"],item["digest"],item["size_in_bytes"]]==spec["artifact"],"different documentation archive")
    arc=root/"source-documentation.zip"
    transport=t.acquire(item,arc,160<<20)
    previous=json.loads((t.STAGE/"documentation-originals.json").read_bytes())
    result={}
    with zipfile.ZipFile(arc) as z:
        t.need(z.testzip() is None and len(z.namelist())==len(set(z.namelist())) and
               sum(i.file_size for i in z.infolist())<350<<20,"excess or duplicate documentation archive")
        for role,park in (("P","normal"),("C","defer")):
            raw=z.read(role+"/receipt.json")
            row=json.loads(raw)
            t.need(hashlib.sha256(raw).hexdigest()==spec["receipts"][role],"different builder receipt")
            key,size=qualification(role,row,previous[role])
            d=root/"doc-products"/role;d.mkdir(parents=True)
            (d/"receipt.json").write_bytes(raw)
            supplied=d/"rustdoc"
            t.unzip_member(z,role+"/rustdoc",supplied,120<<20)
            t.need(supplied.stat().st_size==size and t.sha(supplied)==key,"different actual documentation executable")
            supplied.chmod(0o555)
            installed=root/"parked"/park/"bin/rustdoc"
            os.link(supplied,installed)
            t.need(installed.samefile(supplied) and t.sha(installed)==key,"wrong installed documentation inode")
            result[role]=row
    t.save(root/"docs-qualification.json",{"immutable":spec,"archive":transport,"actual":result})


def exercise(kit,role,where):
    row=kit.docs["actual"][role]
    real=kit.sdk/"bin/rustdoc";reference=kit.inputs/"doc-products"/role/"rustdoc"
    t.need(real.samefile(reference) and t.sha(real)==row["rustdoc"][0],"source documentation changed at selection")
    proxy=Path(subprocess.check_output(["rustup","which","--toolchain","ohm","rustdoc"],env=kit.base,text=True).strip())
    t.need(proxy.samefile(real),"Rustup bypassed the source-matched rustdoc")
    command=["rustdoc","+ohm"]
    vv=subprocess.check_output([*command,"-vV"],env=kit.base,text=True)
    t.need(vv==row["version"],"source documentation command changed version")
    where.mkdir()
    inp=where/"doc_input.rs";inp.write_bytes(DOC_SOURCE)
    out=where/"site"
    p=subprocess.run([*command,"--crate-name","ldv_tool_identity","--edition=2021","-o",out,inp],
                     env={**kit.base,"LD_DEBUG":"libs"},capture_output=True,check=True,timeout=90)
    init=[Path(a) for a in re.findall(r"calling init:\s+([^\s]+)",p.stderr.decode())]
    libs={}
    for key,starts in (("driver","librustc_driver-"),("llvm","libLLVM")):
        hits=[f for f in init if f.name.startswith(starts)]
        expected=kit.refs[role][key]
        t.need(len(hits)==1 and hits[0].samefile(kit.sdk/expected["name"]) and t.sha(hits[0])==expected["sha"],
               "source documentation loaded different compiler bytes")
        libs[key]={"name":expected["name"],"sha":expected["sha"],"opened":str(hits[0])}
    item=out/"ldv_tool_identity/fn.ldv_registry_identity.html"
    t.need(b"Independently emitted documentation for the original compiler kit." in item.read_bytes(),"no actual HTML")
    # Keep the entire item page but avoid duplicating packaged Rustdoc static resources across ordinary slots.
    (where/"actual.html").write_bytes(item.read_bytes())
    shutil.rmtree(out)
    return {"rustdoc":t.sha(real),"id":[real.stat().st_dev,real.stat().st_ino],"version":vv,"source":t.sha(inp),
            "html":t.sha(where/"actual.html"),"actual_libs":libs}
