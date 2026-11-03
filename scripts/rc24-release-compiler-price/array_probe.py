"""Check lowering, byte order, static identity and overflow with each real compiler."""
import json
from pathlib import Path
import subprocess
import sys
root=Path(sys.argv[1]).resolve()
role=sys.argv[2]
assert role in ("parent","candidate")
root.mkdir()
n=1025
vals={"A":[(i*13+11)%256 for i in range(n)],"B":[(i*97+257)%65536 for i in range(n)],
      "C":[(i*2654435761+0x1020304)%2**32 for i in range(n)]}
ty={"A":"u8","B":"u16","C":"u32"}
def source(v):
    return "\n".join([f"static {k}: [{ty[k]}; {n}] = ["+",".join(map(str,v[k]))+"];" for k in v]+[
        f"static OTHER: [u16; {n}] = ["+",".join(map(str,v["B"]))+"];",
        'fn main() { println!("{} {} {} {}", A.iter().map(|&x|u64::from(x)).sum::<u64>(), B.iter().map(|&x|u64::from(x)).sum::<u64>(), C.iter().map(|&x|u64::from(x)).sum::<u64>(), std::ptr::eq(&B, &OTHER)); }'])+"\n"
src=root/"probe.rs"
src.write_text(source(vals))
args=["rustc","+ohm","--edition=2024",str(src)]
trace=subprocess.check_output([*args,"-Zunpretty=thir-tree"],text=True)
count=trace.count("IntArrayLiteral(")
assert count==(4 if role=="candidate" else 0),(role,count)
exe=root/"probe"
cmd=[*args,"-C","incremental="+str(root/"incremental"),"-o",str(exe)]
def run_program(cmd,values):
    subprocess.run(cmd,check=True)
    actual=subprocess.check_output([str(exe)],text=True)
    assert actual==" ".join([str(sum(values[k])) for k in ("A","B","C")]+["false"])+"\n",actual
    return actual
before=run_program(cmd,vals)
pos=n//2
old=vals["A"][pos]
vals["A"][pos]=256
bad=source(vals)
src.write_text(bad)
err=subprocess.run([*cmd,"--error-format=json"],capture_output=True,text=True)
assert err.returncode!=0
diags=[json.loads(l) for l in err.stderr.splitlines() if l.startswith("{")]
hit,=[d for d in diags if d.get("code") and d["code"]["code"]=="overflowing_literals"]
mark,=[s for s in hit["spans"] if s["is_primary"]]
assert bad[mark["byte_start"]:mark["byte_end"]]=="256" and mark["byte_start"]<bad.index("\n")
vals["A"][pos]=(old+1)%256
src.write_text(source(vals))
repaired=run_program(cmd,vals)
empty=run_program([*args,"-o",str(exe)],vals)
assert before!=repaired==empty
(root/"verdict.json").write_text(json.dumps({"marked_arrays":count,"native_old":before,"native_repaired":repaired,
    "native_empty":empty,"invalid":{"message":hit["message"],"byte_start":mark["byte_start"],"byte_end":mark["byte_end"]}},indent=2)+"\n")
