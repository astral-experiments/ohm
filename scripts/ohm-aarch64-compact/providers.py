"""Run the authentic GNU assembler and provider search for the single input-register barrier."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent / 'ohm-aarch64-registers'))
import native
from study import need, save, sha
from native import rt

BARRIER = '''#[inline(always)] fn barrier(value: usize) -> usize {
    unsafe { core::arch::asm!("/* {value} */", value = in(reg) value, options(nomem, nostack)); }
    value
}
'''
DECL = '''#[link(name="qa_ohm_external", kind="static")] unsafe extern "C" {fn qa_value()->i32;}
'''
main = DECL + BARRIER + 'fn main(){println!("{}",barrier(unsafe{qa_value()} as usize));}\n'
bundle = DECL + BARRIER + 'pub fn value()->usize{barrier(unsafe{qa_value()} as usize)}\n'
native.assembly()
native.links(main, bundle)
root = rt.ROOT / "gnu-as"
env = rt.environment()
out = rt.LOG / "spaced-gnu-as"
bodies = []
for i, line in enumerate(("", "/* x19 */", "/* x0 */", "/* x30 */")):
    (root/'spaced.s').write_text(".text\n.globl foo\nfoo:\n"+line+"\nmov w0, #17\nret\n")
    rt.record([native.AS,'-o','spaced.o','spaced.s'],out/str(i)/'as',root,env)
    rt.record([native.COPY,'--only-section=.text','-O','binary','spaced.o','raw'],out/str(i)/'text',root,env)
    bodies.append((root/'raw').read_bytes().hex())
need(len(set(bodies))==1 and bodies[0],"real assembler changed instruction bytes")
save(out/'complete.json',{"text":bodies,"as":sha(Path(native.AS)),"fixture":main})
