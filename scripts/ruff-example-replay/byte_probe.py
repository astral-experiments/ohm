"""Compare whole integration test ELFs on the released binary and both source-built Cargos."""
import gzip
import hashlib
import itertools
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import factory
import study
from factory import need, save, sha

AFFECTED = ("formatter", "ruff", "rustc_tests")
ARGS = ["test", "-p", study.PACKAGE, "--no-run"]


def elf(data):
    need(data[:6] == b"\x7fELF\x02\x01", "ELF64 little endian")
    base = struct.unpack_from("<Q", data, 40)[0]
    step,count,strings = struct.unpack_from("<3H", data, 58)
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, base + i*step) for i in range(count)]
    names = headers[strings][4]
    result = {}
    for ix,row in enumerate(headers):
        name = data[names+row[0]:data.index(b"\0",names+row[0])].decode()
        _,typ,flags,addr,offset,size,_,_,_,_ = row
        value = b"" if typ == 8 else data[offset:offset+size]
        need(name not in result, "unique section " + name)
        result[name] = {"index":ix,"type":typ,"flags":flags,"address":addr,"offset":offset,"size":size,
                        "sha256":hashlib.sha256(value).hexdigest()}
    return result


def materialize(root, out, values, originals):
    captures = {}
    for name in AFFECTED:
        key = "test/" + name + "/True"
        file, expected, length = values[key]
        path = Path(file).resolve(strict=True)
        need(path.is_relative_to(root/"slot"), "physical private test harness")
        data = path.read_bytes()
        need(len(data)==length and hashlib.sha256(data).hexdigest()==expected, "actual captured ELF")
        if expected not in originals:
            selected = root / "raw" / expected
            selected.write_bytes(data)
            selected.chmod(0o755)
            originals[expected] = {"name":name, "size":length, "sections":elf(data)}
            # Preserve each distinct physical ELF once. This diagnostic runs outside all clocks.
            with (out/"objects"/(expected+".zst")).open("xb") as dst:
                subprocess.run(["zstd","-q","-5","-c",selected],stdout=dst,check=True)
            symbols = subprocess.check_output(["nm","-anS","--defined-only",selected])
            (out/"objects"/(expected+"-symbols.gz")).write_bytes(gzip.compress(symbols,mtime=0))
        captures[name] = expected
    return captures


def verdicts(src, env, dest, actual):
    outputs = {}
    dest.mkdir()
    for name, (file, expected, _) in actual.items():
        need(sha(Path(file))==expected,"unchanged behavior-test image")
        result = subprocess.run([file, "--test-threads=1"], cwd=src/"crates"/study.PACKAGE,
                                env=env, capture_output=True, timeout=300)
        case = dest/name
        case.mkdir()
        study.compressed(case/"stdout.gz",result.stdout)
        study.compressed(case/"stderr.gz",result.stderr)
        rows = sorted((a.decode(),b.decode()) for a,b in re.findall(
            rb"^test (.*?) \.\.\. (ok|FAILED|ignored)(?:[^\n]*)$",result.stdout,re.M))
        outputs[name] = {"exit":result.returncode,"cases":rows,"binary":expected}
    return outputs


def difference(root, meta, left, right):
    if left == right:
        return {}
    a=(root/"raw"/left).read_bytes()
    b=(root/"raw"/right).read_bytes()
    as_,bs=meta[left]["sections"],meta[right]["sections"]
    result={}
    for name in as_.keys()|bs.keys():
        x,y=as_.get(name),bs.get(name)
        if x==y:
            continue
        entry={"before":x,"after":y}
        if x and y and x["type"]!=8 and y["type"]!=8 and x["sha256"]!=y["sha256"]:
            lhs=a[x["offset"]:x["offset"]+x["size"]]
            rhs=b[y["offset"]:y["offset"]+y["size"]]
            spots=list(itertools.islice((i for i,(f,s) in enumerate(zip(lhs,rhs)) if f!=s),32))
            entry["differing_bytes_at_common_offsets"]=sum(f!=s for f,s in zip(lhs,rhs))
            entry["first_offsets"]=spots
            if spots:
                n=spots[0]
                lo=max(0,n-24)
                entry["first_context_hex"]=[lhs[lo:n+64].hex(),rhs[lo:n+64].hex()]
        result[name]=entry
    return result


def main():
    ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]==study.BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head,"registered diagnostic")
    for d,h in (("enrolled",head),("historical",study.RENDERER)):
        need(subprocess.check_output(["git","-C",ws/d,"rev-parse","HEAD"]).decode().strip()==h,"actual checkout")
    sys.path.insert(0,str(ws/"historical/scripts/gnu-example-ceiling"))
    import workload as w

    root=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)/"ruff-example-price"
    root.mkdir()
    out=root/"evidence"
    out.mkdir()
    (out/"objects").mkdir()
    (root/"raw").mkdir()
    binaries=factory.recover_factory(root,ws,out)
    binaries["released"]=root/"distribution/bin/cargo"
    cpus=sorted(os.sched_getaffinity(0))
    need(len(cpus)>=4,"same four-CPU policy as original worker")
    os.sched_setaffinity(0,cpus[:4])
    study.select(root,binaries,"released")
    src=w.source(root)
    env=w.env_for(root)
    seed=w.prepare_registry(root,src,env,out)
    patch=Path(w.__file__).parent/"renderer.patch"
    shots={}
    originals={}
    outputs={}
    owners={}
    for arm in ("released","parent","candidate"):
        study.select(root,binaries,arm)
        study.reset(env,seed,w)
        d=out/arm
        d.mkdir()
        w.git(src,"apply","--reverse",patch)
        w.sources(src,"old")
        old=study.execute(root,src,env,d/"old",ARGS)
        shots[arm+"/old"]=materialize(root,out,old["executables"],originals)
        w.git(src,"apply",patch)
        w.sources(src,"corrected")
        study.execute(root,src,env,d/"edit",ARGS)
        warm=study.execute(root,src,env,d/"first-unchanged",ARGS)
        tag=arm+"/warm"
        shots[tag]=materialize(root,out,warm["executables"],originals)
        actual={n:warm["executables"]["test/"+n+"/True"] for n in AFFECTED}
        outputs[tag]=verdicts(src,env,d/"actual-warm",actual)
        w.sources(src,"corrected")
        traced=study.execute(root,src,env,d/"traced-settled",ARGS,trace=True)
        owners[arm]=[r for r in traced["execs"] if r["kind"]=="rustc" and "--crate-name" in r["args"]
                     and r["args"][r["args"].index("--crate-name")+1] in AFFECTED]
        for repeat in range(2):
            study.reset(env,seed,w)
            name="empty-new-"+str(repeat)
            tag=arm+"/"+name
            clean=study.execute(root,src,env,d/name,ARGS)
            shots[tag]=materialize(root,out,clean["executables"],originals)
            actual={n:clean["executables"]["test/"+n+"/True"] for n in AFFECTED}
            outputs[tag]=verdicts(src,env,d/("actual-"+name),actual)
            w.sources(src,"corrected")
    comparisons={}
    for source in shots:
        if source.endswith("/old"):
            continue
        for name in AFFECTED:
            a=shots["released/empty-new-0"][name]
            b=shots[source][name]
            key=a+"-"+b
            if a!=b and key not in comparisons:
                comparisons[key]=difference(root,originals,a,b)
    save(out/"elfs.json",originals)
    save(out/"sections.json",comparisons)
    save(out/"verdicts.json",outputs)
    save(out/"actual-owners.json",owners)
    save(out/"terminal.json",{"run":os.environ["GITHUB_RUN_ID"],"head":head,"shots":shots,
                              "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                              "cpus":cpus[:4],"binaries":{arm:sha(file) for arm,file in binaries.items()}})


if __name__=="__main__":
    main()
