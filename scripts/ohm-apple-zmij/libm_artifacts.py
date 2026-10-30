"""Bind the actual libm registry units to their assembler input markers and callable native math."""
from pathlib import Path
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
            argv=["rustc","+ohm",str(source),"--edition=2021","--extern","libm="+str(archive),"-o",str(program)]
            compiler=subprocess.run(argv,cwd=name,env=env,capture_output=True,timeout=120)
            compress_bytes(name/"compiler.stdout.gz",compiler.stdout);compress_bytes(name/"compiler.stderr.gz",compiler.stderr)
            need(compiler.returncode==0,"failed math consumer: "+compiler.stderr[-700:].decode(errors="replace"))
            actual=subprocess.run([str(program)],cwd=name,env=env,capture_output=True,timeout=25)
            need(actual.returncode==0 and not actual.stderr and actual.stdout==b'3ff6a09e667f3bcd 3fb504f3 4000000000000000 40800000 401a000000000000 40d00000\n',"unexpected libm result")
            save(name/"verified.json",{"argv":argv,"archive":sha(archive),"stdout":actual.stdout.decode(),"exit":actual.returncode,"program":macho_text(program)})
        evidence.append({"path":str(archive),"sha256":sha(archive),"fresh":u["fresh"],"features":u["features"],
                         "hard":MISSING in body,"recheck":RECHECK in body,"dep":digest(body),"source":str(src)})
    need(len({r["path"] for r in evidence})==len(evidence),"duplicate libm output")
    return evidence
