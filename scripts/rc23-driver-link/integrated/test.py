"""Check a Rust-owned export and independently overridable support and C exports on real ELF."""
from pathlib import Path
from hashlib import sha256
import json
import os
import subprocess
import sys

here=Path(__file__).resolve().parent
sdk=Path(sys.argv[1]).resolve()
dest=Path(sys.argv[2]).resolve()
expected=sys.argv[3]
assert expected in ("ordinary","local")
dest.mkdir()
env={**os.environ,"RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(sdk/"lib")}
env.pop("LD_PRELOAD",None)
commands=[]
def run(*argv,more=None):
    p=subprocess.run([str(a) for a in argv],env={**env,**(more or {})},cwd=dest,capture_output=True,text=True)
    commands.append({"argv":list(map(str,argv)),"exit":p.returncode,"stderr":p.stderr[-1000:]})
    if p.returncode:
        print(p.stderr[-1600:],file=sys.stderr)
        raise RuntimeError(argv)
    return p.stdout
rust=sdk/"bin/rustc"
base=[rust,"--edition=2024","-Csymbol-mangling-version=v0","-Ccodegen-units=1","-Cprefer-dynamic=no"]
for name,file in (("rustc_fixture","provider.rs"),("support","support.rs")):
    run(*base,"--crate-name",name,"--crate-type=rlib",here/file,"-o",dest/("lib"+name+".rlib"))
img=dest/"librustc_driver.so"
bind=dest/"binding-policy";bind.mkdir()
(bind/"owners").write_text("rustc_driver\nrustc_fixture\n")
run(*base,"--crate-name","rustc_driver","--crate-type=dylib",here/"driver.rs",
    "--extern","rustc_fixture="+str(dest/"librustc_fixture.rlib"),"--extern","support="+str(dest/"libsupport.rlib"),
    "-o",img,more={"OHM_RUSTC_DRIVER_LINK_DIR":str(bind)})
syms=run("nm","-D","-P","--defined-only",img)
names=[l.split()[0] for l in syms.splitlines() if l.startswith("_R")]
def symbol(end):
    result,=[name for name in names if name.endswith(end)]
    return result
driver=symbol("12driver_value");support=symbol("13support_value")
over=dest/"override.c"
over.write_text(f'unsigned driver(void) __asm__("{driver}");\n'
                f'unsigned support(void) __asm__("{support}");\n'
                'unsigned driver(void) { return 21; }\n'
                'unsigned hook_value(void) { return 22; }\n'
                'unsigned support(void) { return 23; }\n')
run("cc","-shared","-fPIC","-O2",over,"-o",dest/"override.so")
run("cc","-O2",here/"check.c","-ldl","-o",dest/"check")
def probe(preload):
    flags={"LD_PRELOAD":str(dest/"override.so")} if preload else {}
    return list(map(int,run(dest/"check",img,driver,support,more=flags).split()))
normal,preload=probe(False),probe(True)
assert normal==[11,12,13,11,12,13]
want=11 if expected=="local" else 21
relocs=run("readelf","-Wr",img)
result={"rustc_vV":run(rust,"-vV"),"compiler_image":sha256(rust.read_bytes()).hexdigest(),
  "expected":expected,"actual_image":sha256(img.read_bytes()).hexdigest(),"driver_symbol":driver,"support_symbol":support,
  "symbols_sha256":sha256(syms.encode()).hexdigest(),"relocations_sha256":sha256(relocs.encode()).hexdigest(),
  "driver_relocations":[l.strip() for l in relocs.splitlines()if driver in l],
  "support_relocations":[l.strip() for l in relocs.splitlines()if support in l],"normal":normal,"preloaded":preload,
  "commands":commands}
(dest/"result.json").write_text(json.dumps(result,indent=1,sort_keys=True)+"\n")
assert preload==[want,22,23,21,22,23],preload
assert bool(result["driver_relocations"])==(expected=="ordinary") and result["support_relocations"]
lists=list(bind.glob("*.exports"))
assert len(lists)==(expected=="local")
if lists:
    names={line.strip().removesuffix(";") for line in lists[0].read_text().splitlines()}
    assert driver not in names and "hook_value" in names and support in names
print(normal,preload,sha256((dest/"result.json").read_bytes()).hexdigest())
