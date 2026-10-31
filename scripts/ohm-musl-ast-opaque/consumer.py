"""Read the three captured lifetimes through rustc's metadata and link interfaces."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ohm-musl-ast-hardware'))
from clocked import file_sha,require,sha,save

TAIL="chars λ🦀; literals left,right; interpolations 1\n"
BAD={"chars":("StringLiteralValue","char"),"literals":("InterpolatedStringElements","&'a InterpolatedStringLiteralElement"),"interpolations":("InterpolatedStringElements","&'a InterpolatedElement")}


def setup(scratch,original):
    scratch.mkdir()
    code=original.read_text()
    require(code.count("fn main() {")==1 and file_sha(original)=="f9b0f26c4b3e601e474a3b41ff8fd5faf8c5b4898348004534c5ffae05c2941f","original Ruff AST consumer")
    (scratch/"positive.rs").write_text(code.replace("fn main() {","fn visitor() {")+"\n"+(HERE/"consumer.rs").read_text())
    for method,(owner,ret) in BAD.items():
        (scratch/(method+".rs")).write_text("use ruff_python_ast::*;\npub fn escape<'a>(x: &'a "+owner+") -> Box<dyn Iterator<Item = "+ret+"> + 'static> {\n    Box::new(x."+method+"())\n}\n")
    return {p.name:file_sha(p) for p in sorted(scratch.glob("*.rs"))}


def trace_open(lines,path):
    word=b'"'+bytes(path)+b'"'
    return [l for l in lines if word in l and (b"openat(" in l or b"openat2(" in l) and b" = " in l and b" = -1 " not in l]


def check(archive,search,scratch,result,env,expected,frame):
    result.mkdir();out={}
    for mode in ("metadata","archive"):
        original=archive.with_suffix(".rmeta") if mode=="metadata" else archive
        require(original.is_file(),"no real input")
        input_sha=file_sha(original)
        args=["rustc","+ohm","--edition","2024","--crate-name","qa_musl_meta_consumer","--target","x86_64-unknown-linux-musl","-Cdebuginfo=0","--extern","ruff_python_ast="+str(original)]
        for d in search:args+=["-L",d]
        for label in (["positive",*BAD] if mode=="metadata" else ["positive"]):
            seen=scratch/(label+".rs");dest=scratch/("program" if mode=="archive" else "libqa_consumer.rmeta")
            if dest.exists():dest.unlink()
            cmd=args+(["--emit=metadata"] if mode=="metadata" else [])+(["--crate-type=lib"] if label!="positive" else [])+["--error-format=json",str(seen),"-o",str(dest)]
            trace=scratch/"opens.trace"
            run=subprocess.run(["strace","-f","-qq","-yy","-s","65535","-e","trace=execve,execveat,openat,openat2","-o",trace,*cmd],cwd=scratch,env=env,capture_output=True,timeout=120)
            full=trace.read_bytes();part=trace_open(full.splitlines(),original);prefix=result/(mode+"-"+label);record=lambda suffix,text:Path(str(prefix)+suffix).write_bytes(gzip.compress(text,compresslevel=3,mtime=0))
            record(".stdout.gz",run.stdout);record(".stderr.gz",run.stderr);record(".opens.gz",full)
            require(part and file_sha(original)==input_sha,("rustc did not open its enrolled input",mode,label,original))
            compiler=Path(frame["rustc"][0]); driver=Path(frame["driver"][0])
            native_exec=[line for line in full.splitlines() if b'execve("'+bytes(compiler)+b'"' in line and line.endswith(b' = 0')]
            native_driver=[line for line in full.splitlines() if b"openat" in line and b"<"+bytes(driver.resolve(strict=True))+b">" in line and b" = -1" not in line]
            require(native_exec and native_driver and file_sha(driver)==frame["driver"][1],("physical native compiler or driver",mode,label,compiler,driver))
            diag=[json.loads(l) for l in run.stderr.splitlines() if l.startswith(b"{")]
            errors=[d for d in diag if d.get("level")=="error" and d.get("spans")]
            verdict={"argv":cmd,"status":run.returncode,"stderr":sha(run.stderr),"stdout":sha(run.stdout),"input_sha256":input_sha,"path":str(original),"successful_input_opens":len(part),"open_trace":sha(full),"physical_driver":frame,"physical_rustc_execs":len(native_exec),"physical_driver_opens":len(native_driver)}
            if label=="positive":
                require(run.returncode==0 and not errors and dest.is_file(),("positive rejected",mode,[e["message"] for e in errors]))
                verdict["product"]=file_sha(dest)
                if mode=="archive":
                    image=dest.read_bytes()
                    require(image[:7]==b"\x7fELF\x02\x01\x01" and b"INTERP" not in subprocess.check_output(["readelf","-lW",dest]),"real static musl image")
                    got=subprocess.check_output([dest],env=env,timeout=8)
                    require(got.decode()==expected+TAIL,"visitor and all three iterators")
                    record(".reader.gz",image);verdict["reader_stdout"]=got.decode()
            else:
                require(run.returncode==1 and len(errors)==1 and not dest.exists(),("wrong negative outcome",label,run.returncode,errors))
                d=errors[0];spans=[p for p in d["spans"] if p["is_primary"]]
                require(d["message"]=="lifetime may not live long enough" and len(spans)==1 and spans[0]["line_start"]==3 and spans[0]["column_start"]==5 and spans[0]["label"]=="returning this value requires that `'a` must outlive `'static`" and spans[0]["text"][0]["text"].strip()=="Box::new(x."+label+"())","escaped wrong opaque lifetime")
                verdict["diagnostic"]=[d["message"],spans[0]["line_start"],spans[0]["column_start"],spans[0]["label"]]
            out[mode+"/"+label]=verdict
            save(result/(mode+"-"+label+".json"),verdict)
    return out
