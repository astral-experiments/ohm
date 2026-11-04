"""Exercise constant tuples, their native layout, and repeated invalid native builds."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess as sp
import sys
root=Path(sys.argv[1]).resolve();root.mkdir()
src=root/"aggregate.rs";incr=root/"incr"
def source(last):
    a="'x',"*1023;b="(1,'x'),"*1023;c="(1,(2,3)),"*1023;d="(1,2),"*1023
    return (
        "#![deny(overflowing_literals)]\n"+
        f"const CH: &[char] = &[{a}'🦀'];\n"+
        f"const PA: &[(u32,char)] = &[{b}(0xdeadbeef,'λ')];\n"+
        f"const NE: &[(u32,(u16,u16))] = &[{c}(0x12345678,(0xabcd,{last}))];\n"+
        f"const PAD: &[(u32,u8)] = &[{d}(0x98765432,255)];\n"+
        f"const ATTR: &[(u32,char)] = &[{b}#[allow(unused)] (3,'a')];\n"+
        f"const EXPR: &[(u32,char)] = &[{b}(1+2,'a')];\n"+
        "static NAMED_A: [(u32,(u16,u16));1024] = *NEST;\n"+
        "static NAMED_B: [(u32,(u16,u16));1024] = *NEST;\n"+
        f"const NEST: &[(u32,(u16,u16));1024] = &[{c}(42,(14,77))];\n"+
        "const _: () = assert!(CH[1023] == '🦀' && PA[1023].0 == 0xdeadbeef);\n"+
        "fn main() { let i = std::hint::black_box(1023); assert_eq!(PAD[i],(0x98765432,255)); assert_eq!(ATTR[i], EXPR[i]); assert!(!std::ptr::eq(&NAMED_A, &NAMED_B)); println!(\"{:?}\", (CH[i],PA[i],NE[i],NAMED_A[i])); }\n")
args=["rustc","+ohm","--edition=2024",str(src)]
def native(label,last,incremental):
    src.write_text(source(last));exe=root/"program"
    options=["-C","incremental="+str(incr if incremental else root/"empty-incr")]
    sp.run([*args,*options,"-o",exe],check=True)
    output=sp.check_output([exe]).decode().strip()
    assert output==f"('🦀', (3735928559, 'λ'), (305419896, (43981, {last})), (42, (14, 77)))",output
    with exe.open("rb") as f:digest=hashlib.file_digest(f,"sha256").hexdigest()
    shutil.copy2(exe,root/("program-"+label))
    return {"output":output,"elf":digest}
old=native("old","255",True)
thir=sp.check_output([*args,"-Zunpretty=thir-tree"],text=True)
assert thir.count("LiteralArray(")==4,thir.count("LiteralArray(")
bad=source("65536");src.write_text(bad);offset=bad.encode().index(b"65536")
invalid=[]
for _ in range(2):
    result=sp.run([*args,"-C","incremental="+str(incr),"--error-format=json","-o",root/"invalid"],capture_output=True)
    assert result.returncode!=0 and not (root/"invalid").exists()
    messages=[json.loads(l)for l in result.stderr.splitlines() if l.startswith(b"{")]
    message,=[m for m in messages if (m.get("code")or{}).get("code")=="overflowing_literals"]
    span,=[s for s in message["spans"] if s["is_primary"]]
    assert (span["byte_start"],span["byte_end"])==(offset,offset+5)
    invalid.append([message["message"],span["byte_start"],span["byte_end"]])
repair=native("repair","254",True);empty=native("empty","254",False)
assert old!=repair==empty and invalid[0]==invalid[1]
(root/"verdict.json").write_text(json.dumps(dict(marker_count=4,old=old,repair=repair,empty=empty,invalid=invalid),indent=2)+"\n")
