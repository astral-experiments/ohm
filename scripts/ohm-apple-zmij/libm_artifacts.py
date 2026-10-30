"""Bind the actual libm registry units to their assembler input markers and callable native math."""
from pathlib import Path
import json
import subprocess

from study import MISSING, RECHECK, compress_bytes, digest, need, save, sha
from verbs import macho_text

LIB = "d565c5f29ae9f502edca78d536436e85bbc4b955595328a6cfd4a97c1dbbac9b"
ASM = "deb850d77df93beed6dcfcaf67c7665256ae49fc5019fdebc180714ec840cd80"


def audit(units,work,out,env,check_math=False):
    evidence=[]
    for u in units:
        if u["target"]["name"]!="libm" or u["target"]["kind"]!=["lib"]:continue
        src=Path(u["target"]["src_path"])
        need("libm@0.2.16" in u["package_id"] and sha(src)==LIB and sha(src.parent/"math/arch/aarch64.rs")==ASM,
             "wrong linked libm source")
        archive,=[Path(v) for v in u["filenames"] if v.endswith(".rlib")]
        base=archive.stem.removeprefix("lib")+".d"
        locations={(p.stat().st_dev,p.stat().st_ino):p for root in (work/"target",work/"shared") for p in root.rglob(base)}
        dep,=locations.values();body=dep.read_bytes()
        need(b"libm-0.2.16/src/" in body and b"math/arch/aarch64.rs" in body,"absent native AArch64 libm dep-info")
        idx=len(evidence)
        compress_bytes(out/f"libm-{idx}.dep.gz",body)
        if check_math:
            name=out/f"math-{idx}";name.mkdir()
            source=name/"reader.rs";source.write_text('''fn main() {
    let n = std::hint::black_box(2.);
    println!("{:x} {:x} {:x} {:x} {:x} {:x}", libm::sqrt(n).to_bits(), libm::sqrtf(n as f32).to_bits(),
             libm::rint(n + 0.5).to_bits(), libm::rintf(n as f32 + 1.5).to_bits(),
             libm::fma(n, 3.0, 0.5).to_bits(), libm::fmaf(n as f32, 3.0, 0.5).to_bits());
}
''')
            program=name/"reader"
            metadata, = [Path(v) for v in u["filenames"] if v.endswith(".rmeta")]
            need(metadata.is_file() and metadata.stem == archive.stem and metadata.parent == archive.parent,
                 "full libm metadata and archive did not come from the same typed output")
            root=next(p for p in out.parents if p.name=="receipts").parent
            from cgu_inputs import stash
            actual_archive=stash(root,"libm-rlibs",archive.read_bytes())
            actual_metadata=stash(root,"libm-metadata",metadata.read_bytes())
            type_source=name/"types.rs"
            type_source.write_text("pub fn f(x:f64)->f64 { libm::sqrt(x) + libm::rint(x) + libm::fma(x,x,x) }\n")
            bad_dir=name/"bad-metadata";bad_dir.mkdir()
            bad=bad_dir/metadata.name;bad.write_bytes(b"not rustc metadata\n")
            checks={}
            for what,path,expected_status in (("real",metadata,0),("corrupt",bad,1)):
                prefix=["rustc","+ohm",str(type_source),"--edition=2021","--crate-type=lib","--emit=metadata",
                        "--error-format=json","--extern","libm="+str(path),"-o",str(name/(what+".rmeta"))]
                result=subprocess.run(prefix,cwd=name,env=env,capture_output=True,timeout=120)
                compress_bytes(name/(what+"-metadata.stdout.gz"),result.stdout);compress_bytes(name/(what+"-metadata.stderr.gz"),result.stderr)
                codes=[(json.loads(line).get("code") or {}).get("code") for line in result.stderr.splitlines() if line.startswith(b"{")]
                need(result.returncode==expected_status and (expected_status==0 or
                     any(c in ("E0463","E0786") for c in codes) and b"libm" in result.stderr),
                     "independent full libm metadata consumer or corrupt-input rejection failed")
                checks[what]={"argv":prefix,"file":sha(path),"exit":result.returncode,"diagnostics":codes}
            argv=["rustc","+ohm",str(source),"--edition=2021","--extern","libm="+str(archive),
                  "--extern","libm="+str(metadata),"-o",str(program)]
            compiler=subprocess.run(argv,cwd=name,env=env,capture_output=True,timeout=120)
            compress_bytes(name/"compiler.stdout.gz",compiler.stdout);compress_bytes(name/"compiler.stderr.gz",compiler.stderr)
            need(compiler.returncode==0,"failed math consumer: "+compiler.stderr[-700:].decode(errors="replace"))
            actual=subprocess.run([str(program)],cwd=name,env=env,capture_output=True,timeout=25)
            need(actual.returncode==0 and not actual.stderr and actual.stdout==b'3ff6a09e667f3bcd 3fb504f3 4000000000000000 40800000 401a000000000000 40d00000\n',"unexpected libm result")
            compress_bytes(name/"run.stdout.gz",actual.stdout);compress_bytes(name/"run.stderr.gz",actual.stderr)
            executable=stash(root,"libm-math-programs",program.read_bytes())
            save(name/"verified.json",{"argv":argv,"archive":actual_archive,"metadata":actual_metadata,"metadata_tests":checks,
                 "stdout":actual.stdout.decode(),"exit":actual.returncode,"program":macho_text(program),"stored_program":executable})
        evidence.append({"path":str(archive),"sha256":sha(archive),"fresh":u["fresh"],"features":u["features"],
                         "hard":MISSING in body,"recheck":RECHECK in body,"dep":digest(body),"source":str(src)})
    need(len({r["path"] for r in evidence})==len(evidence),"duplicate libm output")
    return evidence
