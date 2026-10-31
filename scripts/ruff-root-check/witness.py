"""Validate complete reported artifacts, real extern paths and a metadata-only downstream client."""
import gzip
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import struct
import zlib
import zipfile

from graph import PROVIDERS, digest, encoded, need

HERE = Path(__file__).resolve().parent
SIZE = {"A":64,"B":56}


def file_sha(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def write_gz(path, payload):
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw,mode="wb",compresslevel=2,mtime=0) as out:
        out.write(payload)


def read_gz(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def diagnostics(messages):
    # Keep the full diagnostic, including rendered source, all child diagnostics and all spans.
    # Cargo may emit messages from parallel jobs in either order.
    return sorted((r for r in messages if r["reason"]=="compiler-message"),key=encoded)


PARSER="crates/ruff_python_parser/src/lib.rs"
PARSER_BYTES={False:"ee24a1933840a400c4730778a5c222d30c36d4b1b4f96bd97b502acfc07a4875", True:"3fbac7f54be2b5cd47eee1993f11e6d58724e32301c0ba3e5afb624562283ab5"}


def source_check(source,invalid):
    need(source["parser_sha256"]==PARSER_BYTES[invalid] and source["status"]==("M "+PARSER if invalid else ""),"different actual parser source bytes")


def type_error(messages,marker,allowed_paths):
    errors=[m for m in messages if m['level']=='error'];coded=[m for m in errors if m.get('code')]
    plain=[m for m in errors if not m.get('code')]
    need(len(coded)==1 and coded[0]['code']['code']=='E0308' and len(plain)<=1 and
         all(m.get('message')=='aborting due to 1 previous error' and m.get('spans')==[] and not m.get('children') for m in plain),
         'unexpected additional compiler error or wrong type diagnosis')
    primary=[s for s in coded[0]['spans'] if s['is_primary']]
    need(primary and all(s['file_name'] in allowed_paths for s in primary) and
         any(marker in text['text'] for s in primary for text in s['text']), 'incorrect primary span or expression')


def error_check(diags,cwd):
    type_error([r['message'] for r in diags],'ohm_branch_switch_invalid',{PARSER,str(cwd/PARSER)})
    need(all(r['target']['name']=='ruff_python_parser' for r in diags if r['message']['level']=='error'),'unexpected compiler error target')


def keep(path, cert, directory):
    directory.mkdir(exist_ok=True)
    target=directory/(cert[1]+".zst")
    if target.exists():
        return
    with target.open("xb") as out:
        subprocess.run(["zstd","-q","-T1","-1","-c",path],stdout=out,check=True)


def verify_bodies(directory):
    for archive in sorted(directory.glob("*.zst")):
        with subprocess.Popen(["zstd","-dcq",archive],stdout=subprocess.PIPE) as p:
            actual=hashlib.file_digest(p.stdout,"sha256").hexdigest()
            need(p.wait()==0 and actual==archive.stem, ("damaged retained complete file",archive))


def enrolled_path(file,work):
    return file.is_absolute() and any(file.resolve().is_relative_to(work/n) for n in ("target","build"))


def file_record(file,work):
    file=Path(file)
    need(enrolled_path(file,work) and file.is_file(), ("foreign/missing Cargo product",file))
    return file.relative_to(work).as_posix(),[file.stat().st_size,file_sha(file)]


def files(messages, work):
    items={}
    path=lambda r:r["reason"]=="compiler-artifact"
    for row in filter(path, messages):
        need(bool(row["filenames"]),("unit without artifact",row["target"]["name"]))
        for file in map(Path,row["filenames"]):
            rel,data=file_record(file,work)
            need(items.setdefault(rel,data)==data,("inconsistent reported file",rel))
    return items


def matched_products(actual, expected, work, originals, retained, where):
    changed={p:[expected.get(p),actual.get(p)] for p in sorted(expected.keys()|actual.keys()) if expected.get(p)!=actual.get(p)}
    write_gz(where/"differences.json.gz",encoded(changed))
    if changed:
        for p,(before,after) in changed.items():
            if before:
                src=originals/(before[1]+".zst")
                out=retained/src.name
                if not out.exists():shutil.copyfile(src,out)
            if after:keep(work/p,after,retained)
    return changed


def owner(physical, cwd, workspace, arm):
    found=[r for r in physical["rustcs"] if r["crate"]=="ruff_dev" and r["mode"]=="full" and
           any((cwd/v).resolve()==cwd/"crates/ruff_dev/src/main.rs" for v in r["argv"] if v.endswith("main.rs"))]
    need(len(found)==1,("unambiguous actual root ruff_dev rustc",len(found)))
    row=found[0];argv=row["argv"]
    need(any(v in ("ohm-branch-cache=yes","-Zohm-branch-cache=yes") for v in argv)==arm.endswith("on"),"wrong physical ruff_dev switch mode")
    need("--emit=dep-info,metadata" in argv and "-Zohm-check-relink-inputs" in argv and
         sum(k.startswith(("incremental=","-Cincremental=")) for k in argv)==1, "not a native incremental root check")
    providers={}
    arguments=[argv[i+1] for i,v in enumerate(argv[:-1]) if v=="--extern"]
    for name in PROVIDERS:
        candidates=[Path(a.split("=",1)[1]) for a in arguments if a.startswith(name+"=")]
        need(len(candidates)==1 and candidates[0].suffix==".rmeta" and enrolled_path(candidates[0],workspace),
             ("ambiguous/nonmetadata ruff_dev provider",name,candidates))
        providers[name]=str(candidates[0])
    search=[argv[i+1] for i,v in enumerate(argv[:-1]) if v=="-L" and argv[i+1].startswith("dependency=")]
    need(search and all(enrolled_path(Path(a.split("=",1)[1]),workspace) for a in search),"unbound actual dependency search")
    return {"pid":row["pid"],"providers":providers,"search":search}


def provider_files(mapping,messages,work):
    need(set(mapping["providers"])==set(PROVIDERS),"missing real reader provider")
    out={}
    for name in PROVIDERS:
        wanted=Path(mapping["providers"][name])
        rows=[r for r in messages if r["reason"]=="compiler-artifact" and r["target"]["name"]==name and
              any(Path(f)==wanted and Path(f).samefile(wanted) for f in r["filenames"])]
        need(len(rows)==1,("actual --extern did not match exactly one JSON artifact",name,rows))
        rel,data=file_record(wanted,work)
        need(data[0]>1024,"empty reader input")
        out[name]={"relative":rel,"file":data,"features":rows[0]["features"],"profile":rows[0]["profile"]}
    return out


def listing(name, path, body, stdout, stderr, code):
    """Bind the metadata decoder's own crate header and complete streams to its input file."""
    need(code==0 and stderr==b"" and body[0]>1024 and re.fullmatch("[0-9a-f]{64}",body[1]),"missing metadata or failed/warning-producing compiler listing")
    lines=stdout.decode().splitlines()
    need(len(lines)>12 and lines[0]=="Crate info:" and lines.count("Crate info:")==1 and lines.count("=External Dependencies=")==1 and
         re.fullmatch(r"name "+re.escape(name)+r"(?:-[0-9a-f]{16})?",lines[1]) and
         Path(path).name=="lib"+lines[1].removeprefix("name ")+".rmeta" and
         re.fullmatch(r"private hash [0-9a-f]{32} stable_crate_id StableCrateId\([0-9]+\)",lines[2]) and
         re.fullmatch(r"public_hash [0-9a-f]{32}",lines[3]) and lines[4:6]==["proc_macro false","triple x86_64-unknown-linux-gnu"],
         "the selected provider, root header, architecture or dependency listing differs")
    return {"argv":["rustc","+ohm","-Zls=root",str(path)],"status":code,"input":body,
            "stdout_sha256":hashlib.sha256(stdout).hexdigest(),"stderr_sha256":hashlib.sha256(stderr).hexdigest()}


STUBS={
    "stdlib/functools.pyi":("vendor/typeshed/stdlib/functools.pyi","0a9e5b203ef44812cd48a115f5fceafaffc2b0c0b013a1de927e2660865a10c5"),
    "stdlib/ty_extensions/_internal.pyi":("ty_extensions/_internal.pyi","6f943618778aa969f0f3dd831181691c74e39af9f28643ebb9db4984907f98b1"),
}


def read_typeshed(path):
    with zipfile.ZipFile(path) as z, path.open("rb") as f:
        names=z.namelist()
        need(len(names)==len(set(names)) and len(names)>500 and set(STUBS)<=set(names),"generated typeshed inventory")
        out={}
        for name,(_,expected) in STUBS.items():
            info=z.getinfo(name)
            need(0<info.file_size<2**20 and 0<info.compress_size<2**20,"unexpected native stub geometry")
            if info.compress_type==93:
                f.seek(info.header_offset);header=f.read(30)
                need(header[:4]==b"PK\x03\x04" and int.from_bytes(header[8:10],"little")==93,"wrong ZIP local member")
                n,e=struct.unpack_from("<HH",header,26)
                need(f.read(n).decode()==name,"central/local ZIP name mismatch")
                f.seek(e,1);raw=subprocess.check_output(["zstd","-dcq"],input=f.read(info.compress_size))
            else:
                need(info.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),"unregistered ZIP codec")
                raw=z.read(info)
            h=hashlib.sha256(raw).hexdigest()
            need(len(raw)==info.file_size and zlib.crc32(raw)==info.CRC and h==expected,("changed generated stub",name))
            out[name]=h
        return {"entries":len(names),"ordered_names":digest(names),"source_members":out}


def typeshed(messages,work,cwd,where):
    selected=[Path(r["out_dir"])/"zipped_typeshed.zip" for r in messages if r["reason"]=="build-script-executed" and
              r["package_id"].startswith("path+"+cwd.as_uri()+"/crates/ty_vendored#")]
    need(len(selected)==1,"missing real ty_vendored archive")
    f=selected[0];rel,cert=file_record(f,work)
    for src,expected in STUBS.values():need(file_sha(cwd/"crates/ty_vendored"/src)==expected,"wrong historical typeshed source")
    return rel,cert,read_typeshed(f)


def check_client(mapping,branch,env,cwd,private,where):
    target=private/"typed-client";target.mkdir(exist_ok=True)
    src=target/"reader.rs";out=target/"libroot_checked.rmeta"
    externs=[arg for n in PROVIDERS for arg in ("--extern",n+"="+mapping["providers"][n])]
    deps=[arg for a in mapping["search"] for arg in ("-L",a)]
    cmd=["rustc","+ohm","--crate-name","root_checked","--crate-type=lib","--edition=2024",
         "--emit=metadata","--error-format=json",str(src),*externs,*deps,"-o",str(out)]
    rows={}
    for size in (64,56):
        label="layout-"+str(size)
        src.write_bytes((HERE/"reader.rs").read_bytes().replace(b"EXPECTED",str(size).encode()))
        out.unlink(missing_ok=True)
        r=subprocess.run(cmd,env=env,cwd=cwd,capture_output=True,timeout=120)
        write_gz(where/(label+".stderr.gz"),r.stderr)
        write_gz(where/(label+".stdout.gz"),r.stdout)
        ok=size==SIZE[branch]
        need(r.returncode==int(not ok) and not r.stdout,"wrong real typecheck status")
        js=[json.loads(l) for l in r.stderr.splitlines()]
        if ok:
            need(not js and out.is_file() and out.stat().st_size>1024,"positive did not emit usable metadata")
            src_file=where/(label+".rmeta")
            shutil.copyfile(out,src_file)
            rows[label]={"status":0,"body":[src_file.stat().st_size,file_sha(src_file)]}
        else:
            need(not out.exists(),"opposite layout unexpectedly emitted a file")
            type_error(js,"EXPRESSION_BYTES",{str(src)})
            rows[label]={"status":1,"diagnostics":digest(js)}
        (where/(label+".command.json")).write_bytes(encoded({"argv":cmd,"code":r.returncode,"source_sha256":file_sha(src)}))
    return rows
