"""Open the previous compiler's real rlib and incremental directory in both directions."""
import hashlib
import json
from pathlib import Path
import subprocess

def need(x, why):
    if not x:
        raise ValueError(why)
def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()
def check(out, arms, env, epochs, simulate_old_header=False):
    out.mkdir()
    proof = {}
    for before, after in [("P","C"),("C","P")]:
        case = out/(before+after)
        case.mkdir()
        flag = 97 if before=="P" else 98
        payload = bytearray(b"x"*65537)
        payload[32768]=flag
        (case/"data").write_bytes(payload)
        (case/"lib.rs").write_text('pub const B: &[u8; 65537] = include_bytes!("data");\n')
        (case/"main.rs").write_text('extern crate epoch; fn main(){println!("{}",epoch::B[32768]);}\n')
        def step(role, label, argv):
            p = subprocess.run([str(arms[role]/"bin/rustc"),*argv],cwd=case,env=env | {"LD_LIBRARY_PATH":str(arms[role]/"lib")},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            (case/(label+".stdout")).write_bytes(p.stdout)
            (case/(label+".stderr")).write_bytes(p.stderr)
            need(p.returncode==0,(label,p.stderr.decode(errors="replace")[-1200:]))
            return p
        base = ["lib.rs","--crate-name","epoch","--crate-type","rlib","-Cmetadata=literal-epoch","-Cincremental=inc","-Zincremental-info"]
        step(before,"first",base)
        rlib=case/"libepoch.rlib"
        original_rlib=digest(rlib)
        # This consumer really decodes the upstream constant under the opposite compiler.
        step(after,"foreign",["main.rs","--extern","epoch=libepoch.rlib","-o","foreign"])
        native=subprocess.check_output([case/"foreign"],cwd=case,env=env)
        need(native==str(flag).encode()+b"\n","foreign rlib returned stale bytes")
        def headers():
            return {str(p.relative_to(case)):p.read_bytes()[:6] for p in (case/"inc").rglob("dep-graph.bin")}
        def magic(v):
            return b"RSIC"+v.to_bytes(2,"little")
        previous=headers()
        need(len(previous)==1 and set(previous.values())=={magic(epochs[before])},("wrong original physical epoch",previous))
        if simulate_old_header:
            # Local calibration only. The real factory exchanges the pristine original directories.
            for p in (case/"inc").rglob("*.bin"):
                with p.open("r+b") as f:
                    if f.read(4)==b"RSIC":f.write((1).to_bytes(2,"little"))
        repeat=step(after,"transition",base)
        now=headers()
        changed={k:v for k,v in now.items() if k not in previous or v!=previous[k]}
        need(changed and set(changed.values())=={magic(epochs[after])},("wrong rebuilt physical epoch",changed,now))
        need(b"Wrong HEADER_FORMAT_VERSION" in repeat.stderr,("old incremental data was not explicitly refused",repeat.stderr[:250]))
        proof[before+after]={"old_graphs":{k:v.hex() for k,v in previous.items()},"new_graphs":{k:v.hex() for k,v in changed.items()},
            "producer_before":original_rlib,"producer_after":digest(rlib),"foreign_elf":digest(case/"foreign"),"foreign_stdout":native.decode(),"simulated":simulate_old_header}
    return proof
