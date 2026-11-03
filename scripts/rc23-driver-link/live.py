"""Probe real function pointers by address, without calling the selected compiler functions."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g

def choose(elf,arm,exceptions):
    chosen={}
    for group in ("compiler","foreign"):
        options=[]
        for name,row in elf["probes"].items():
            if row["pool"]!=group:continue
            if exceptions is not None and (name in exceptions)!=(group=="foreign"):continue
            local=arm=="T" and group=="compiler"
            named=[p for p in row["slots"] if p[1] in (1,6)]
            rel=[p for p in row["slots"] if p[1]==8]
            if (local and rel and not named) or (not local and named):
                slots=rel if local else named
                options.append((len(name),name,{"pool":group,"name":name,"value":row["value"],"slots":slots,"locally_bound":local}))
        assert options,("no actual unaliased function with a physical "+group+" pointer",arm)
        chosen[group]=min(options)[2]
    return chosen

def read(infile):
    q=g.read(infile);image=Path(q["driver"]);lib=ctypes.CDLL(str(image),mode=os.RTLD_NOW|os.RTLD_GLOBAL)
    libc=ctypes.CDLL(None);ds=libc.dlsym;ds.argtypes=(ctypes.c_void_p,ctypes.c_char_p);ds.restype=ctypes.c_void_p
    di=libc.dlinfo;di.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p))
    link=ctypes.c_void_p();assert di(lib._handle,2,ctypes.byref(link))==0
    base=ctypes.c_size_t.from_address(link.value).value
    maps=[line.split(None,5) for line in Path("/proc/self/maps").read_text().splitlines()]
    preload=os.environ.get("OHM_NATIVE_OVERRIDE");h=ctypes.CDLL(preload) if preload else None
    obs={}
    for label,row in q["selection"].items():
        n=row["name"].encode();ours=ds(lib._handle,n);assert ours==base+row["value"]
        region,=[r for r in maps if int(r[0].split("-")[0],16)<=ours<int(r[0].split("-")[1],16)]
        assert "x" in region[1] and Path(region[5]).samefile(image)
        foreign=ds(h._handle,n) if h else None
        if h:assert foreign!=ours and ds(None,n)==foreign
        expected=ours if not h or row["locally_bound"] else foreign
        assert all(ctypes.c_size_t.from_address(base+p[0]).value==expected for p in row["slots"])
        obs[label]={"driver_dlsym":True,"external_override":bool(h),"slots":len(row["slots"]),"overridden":bool(h) and expected==foreign}
    print(json.dumps(obs,sort_keys=True))

def probe(image,elf,arm,exceptions,tmp):
    selected=choose(elf,arm,exceptions);q=tmp/"dynamic-probe.json";g.save(q,{"driver":str(image),"selection":selected})
    source=tmp/"override.c";shim=tmp/"override.so"
    source.write_text("\n".join('void override_'+key+'(void) __asm__("'+row["name"]+'"); void override_'+key+'(void) {}' for key,row in selected.items())+"\n")
    subprocess.run(["cc","-O1","-shared","-fPIC",source,"-o",shim],check=True)
    cmd=[sys.executable,"-ISB",str(Path(__file__).resolve()),str(q)]
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","LD_LIBRARY_PATH":str(image.parent)}
    normal=json.loads(subprocess.check_output(cmd,env=env|{"LD_PRELOAD":str(image)}))
    pre=json.loads(subprocess.check_output(cmd,env=env|{"LD_PRELOAD":str(shim)+":"+str(image),"OHM_NATIVE_OVERRIDE":str(shim)}))
    assert pre["foreign"]["overridden"] and pre["compiler"]["overridden"]==(arm=="R")
    return {"arm":arm,"driver_sha256":elf["sha256"],"selection":selected,"preloaded":pre,"normal":normal,"shim_sha256":g.sha(shim)}

if __name__=="__main__":read(Path(sys.argv[1]))
