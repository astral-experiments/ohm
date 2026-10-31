"""Reopen the original physical archive, direct rustc reads, diagnostics, and static iterator oracle per admitted visit."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from clocked import require, sha
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"ohm-musl-ast-opaque"))
import consumer, verified_state

VISITS=("old","replay-old","measured-final","empty","empty-again","replay-edit","repair")
EDGES=(("empty","measured-final"),("empty","empty-again"),("measured-final","empty-again"),("old","replay-old"),("replay-edit","empty"),("repair","empty"))

def static_output(image):
    require(image[:7]==b"\x7fELF\x02\x01\x01","static iterator-reader ELF")
    fd=os.memfd_create("ohm-sealed-typed-visitor",flags=getattr(os,"MFD_EXEC",0))
    try:
        with os.fdopen(os.dup(fd),"wb") as f:f.write(image)
        os.fchmod(fd,0o500)
        try:run=subprocess.run(["/proc/self/fd/"+str(fd)],pass_fds=(fd,),env={"LC_ALL":"C"},capture_output=True,timeout=10)
        except PermissionError:
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/"verified-musl-visitor";path.write_bytes(image);path.chmod(0o500)
                require(sha(path.read_bytes())==sha(image),"temporary native image")
                run=subprocess.run([path],env={"LC_ALL":"C"},capture_output=True,timeout=10)
        require(run.returncode==0 and not run.stderr,"real retained musl static client")
        return run.stdout.decode()
    finally:os.close(fd)

def verify(arm,term,opaque,raw):
    def doc(n):return json.loads(raw(arm+n))
    def data(n):return gzip.decompress(raw(arm+n))
    checks={}
    require(set(term["artifacts"])==set(VISITS) and set(term["opaque_readers"])==set(VISITS), "complete lifetime and replica-clean visits")
    for n in VISITS:
        prefix="proof/"+n+"/";state=term["artifacts"][n]
        manifest=doc(prefix+"ar-replay.json")
        checks[n]=verified_state.witness(manifest,lambda h:data("proof/ar-content/"+h+".gz"))
        stream=term["opaque_readers"][n]
        require(set(stream)=={"metadata/positive","archive/positive",*("metadata/"+k for k in consumer.BAD)},"incomplete typed outcomes")
        for mode_method,small in stream.items():
            mode,method=mode_method.split("/");base="lifetimes/"+n+"/"+mode+"-"+method
            j=doc(base+".json");sr=term["artifacts"][n]["rmeta" if mode=="metadata" else "rlib"]
            for attr in small:require(j.get(attr)==small[attr],("summary does not reopen",attr))
            args=j["argv"]; i=args.index("--extern")
            require(j["input_sha256"]==sr and args[i+1]=="ruff_python_ast="+j["path"] and j["successful_input_opens"]>0,"typed real archive/rmeta")
            opens=data(base+".opens.gz");stderr=data(base+".stderr.gz");stdout=data(base+".stdout.gz")
            require(sha(opens)==j["open_trace"] and sha(stdout)==j["stdout"] and sha(stderr)==j["stderr"]
                    and len(consumer.trace_open(opens.splitlines(),Path(j["path"])))==j["successful_input_opens"],"actual native kernel read or raw diagnostics changed")
            rust,driver=(j["physical_driver"][k][0] for k in ("rustc","driver"))
            rustcs=[l for l in opens.splitlines() if b'execve("'+rust.encode()+b'"' in l and l.endswith(b' = 0')]
            drivers=[l for l in opens.splitlines() if b'openat' in l and b'<'+driver.encode()+b'>' in l and b' = -1' not in l]
            require(len(rustcs)==j["physical_rustc_execs"] and len(drivers)==j["physical_driver_opens"] and rustcs and drivers
                and j["physical_driver"]["driver"][1]==term["driver"]["sha256"],"missing actual compiler and driver")
            ds=[json.loads(l) for l in stderr.splitlines() if l.startswith(b"{")]
            errors=[d for d in ds if d.get("level")=="error" and d.get("spans")]
            if method=="positive":
                require(j["status"]==0 and not errors and len(j["product"])==64,"physical positive")
                if mode=="archive":
                    src="old" if n in ("old","replay-old") else "new"
                    require(j["product"]==opaque["native_outputs"][src],"wrong independently accepted augmented ELF")
                    image=data("lifetime-images/"+j["product"]+".elf.gz")
                    require(sha(image)==j["product"] and static_output(image)==state["result"]+consumer.TAIL==j["reader_stdout"],"actual visitor execution or iterator payload")
            else:
                require(j["status"]==1 and len(errors)==1,"missing lifetime error")
                error=errors[0];span,=[x for x in error["spans"] if x["is_primary"]]
                require(j["diagnostic"]==[error["message"],span["line_start"],span["column_start"],span["label"]]
                    ==["lifetime may not live long enough",3,5,"returning this value requires that `'a` must outlive `'static`"]
                    and span["text"][0]["text"].strip()=="Box::new(x."+consumer.BAD[method][2]+"())","different method, borrowed expression or diagnostic")
    outcomes={}
    for a,b in EDGES:
        label=a+"--"+b
        fresh=verified_state.compare(a,b,term["artifacts"][a],term["artifacts"][b],checks[a],checks[b])
        require(fresh==doc("archive-comparisons/"+label+".json")==term["archive_comparisons"][label],"complete original archive reconstruction")
        outcomes[label]=fresh["strict_differences"]
    return outcomes
