"""Charge all proof construction and answers to the one genuine Cargo command."""
from collections import defaultdict
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "workspace-link-proof"))
import bound_roster

HASH = re.compile(r"[0-9a-f]{64}")
FAIL = (KeyError, ValueError, IndexError, TypeError, AssertionError, OSError)


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def atom(path, raw):
    tmp = path.with_suffix(".pending")
    with tmp.open("xb") as f:
        f.write(raw)
    tmp.replace(path)


def rows(raw):
    out = defaultdict(list)
    for line in raw.splitlines():
        k, *v = line.split("\t")
        out[k].append(v)
    return out


def before(raw, specs, image):
    observed = rows(raw)
    args = [json.loads(arg) for pos, arg in observed["ARG"]]
    dest = args[args.index("-o")+1]
    (role,) = [k for k in specs if dest.endswith(k)]
    proof, original = bound_roster.receive(raw, {**specs[role], "suffix":role})
    assert original == args
    groups = [list(map(int, g)) for g in observed["PROJECTED-GROUP"]]
    (g,) = observed["GROUPINPUT"]
    (typed,) = observed["TYPED"]
    assert len(typed)==7 and len(g)==5 and HASH.fullmatch(g[-1])
    assert groups and len(groups)==int(g[3]) and all(len(r)==2 and r[0]>0 and r[1]>=0 for r in groups)
    assert sum(r[0] for r in groups)==int(typed[0]) and sum(r[1] for r in groups)==int(g[0])
    allowed = observed["DOMAINS"]==[["true","true","1"]] and observed["ADMISSION"]==[["true",image]]
    key=hashlib.sha256(encode(["physical-native-48-v1",proof["key"],groups])).hexdigest()
    return {"role":role,"path":dest,"key":key,"parts":proof["parts"],"groups":groups,
            "allowed":allowed,"input_bytes":proof["bytes"],"inputs":proof["inputs"],"missed":proof["denied_lookups"]}


class Blake3:
    def __init__(self, path):
        self.api=ctypes.CDLL(str(path))
        ptr=ctypes.c_void_p
        self.init=self.api.llvm_blake3_hasher_init
        self.update=self.api.llvm_blake3_hasher_update
        self.final=self.api.llvm_blake3_hasher_finalize
        for f,types in ((self.init,[ptr]),(self.update,[ptr,ptr,ctypes.c_size_t]),(self.final,[ptr,ptr,ctypes.c_size_t])):
            f.argtypes=types; f.restype=None
        assert self.digest(())=="af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"

    def digest(self, chunks):
        state=(ctypes.c_uint64*512)()
        out=(ctypes.c_ubyte*32)()
        self.init(state)
        for chunk in chunks:
            self.update(state,chunk,len(chunk))
        self.final(state,out,32)
        return bytes(out).hex()


def file_identity(st):
    return [st.st_dev,st.st_ino,st.st_size,st.st_ctime_ns,st.st_mode,st.st_nlink]


def current_file(parsed, fields, hashed):
    dev,ino,n,digest,path=fields
    assert path==parsed["path"] and HASH.fullmatch(digest)
    p=Path(path); before=file_identity(p.lstat())
    assert before[:3]==[int(dev),int(ino),int(n)] and stat.S_ISREG(before[4]) and before[5]==1
    assert 1<<20<=int(n)<=250<<20
    if hashed is not None:
        fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            assert file_identity(os.fstat(fd))==before
            total=0
            def chunks():
                nonlocal total
                while block:=f.read(1<<20):
                    total+=len(block)
                    assert total<=int(n)
                    yield block
            assert hashed.digest(chunks())==digest and total==int(n)
            assert file_identity(os.fstat(fd))==before==file_identity(p.lstat())
    return {"dev":int(dev),"ino":int(ino),"size":int(n),"output":digest}


def finish(text, parsed, response, old, hashed, tag):
    obs=rows(text); predicted=[list(map(int,x)) for x in obs["PROJECTED-GROUP"]]
    actual=[list(map(int,x)) for x in obs["ACTUAL-GROUP"]]
    assert predicted==parsed["groups"] and obs["VERIFIED"]==[[]] and len(obs["EMITTED"])==1
    fresh=bool(obs["FRESH-PUBLISH"])
    reasons=[x[0] for x in obs["MISS"]]
    assert len(obs["FRESH-PUBLISH"])<=1 and not obs["REFUSED"] and not obs["WARNING"]
    if fresh:
        assert parsed["allowed"] and response=="verify" and old["key"]==parsed["key"]
        assert not actual and len(obs["ACCEPT"])==len(obs["FRESH-GENERATIONS"])==1
        a=obs["ACCEPT"][0]
        assert [int(x) for x in a[:3]]==[old["dev"],old["ino"],old["size"]] and a[3]==old["output"]
        d,i,size,blocks,nlinks,opened_d,opened_i,named_d,named_i=map(int,obs["FRESH-GENERATIONS"][0])
        assert (d,i)==(old["dev"],old["ino"])!=(opened_d,opened_i)==(named_d,named_i)
        assert size==old["size"] and blocks>0 and nlinks==0
        file=current_file(parsed,obs["EMITTED"][0],None)
        assert (file["dev"],file["ino"])==(named_d,named_i) and file["size"]==old["size"] and file["output"]==old["output"]
        prior_source=old["full_stage"]
        held=blocks*512
    else:
        assert actual==predicted and not obs["FRESH-PUBLISH"]
        # On an unsupported input/old writer configuration there is no donor to enroll.
        if not parsed["allowed"]:
            return None,{"action":"full-typed-refusal","reasons":reasons,"held_allocated":0}
        file=current_file(parsed,obs["EMITTED"][0],hashed)
        prior_source=tag
        held=0
    return {**file,"key":parsed["key"],"full_stage":prior_source}, {
        "action":"fresh" if fresh else "full","reasons":reasons,"held_allocated":held,
        "physical":file,"from_full_stage":prior_source,"donor_bytes_read_after_emission":0 if fresh else file["size"]}


def main():
    state,report,image,llvm,tag,kind,memory,real,*command=sys.argv[1:]
    state,report=Path(state),Path(report)
    assert kind in ("allow","full") and not report.exists() and HASH.fullmatch(image)
    assert command[0]=="cargo" and command[1:3]==["+ohm","test"] and Path(real).is_absolute()
    assert state.is_dir() and not state.is_symlink() and (state/"coordinate").is_file()
    assert not list(state.glob("actor-*.tsv")) and not list(state.glob("ready-*"))
    lib=ctypes.CDLL(None,use_errno=True); assert lib.prctl(36,1,0,0,0)==0 # PR_SET_CHILD_SUBREAPER
    allspec=json.loads((HERE.parent/"workspace-link-proof/roles.json").read_bytes())
    allow=json.loads((HERE/"accepted-48.json").read_bytes())
    specs={k:allspec[k] for k in allow}; assert len(specs)==48
    memory=int(memory)
    assert os.readlink("/proc/self/fd/"+str(memory))=="/memfd:ohm-bounded-links (deleted)"
    os.set_inheritable(memory,False)
    limit=64<<10
    start_size=os.fstat(memory).st_size
    assert 0<=start_size<=limit
    packet=os.pread(memory,limit,0)
    prior={}
    if len(packet)>=32 and hashlib.sha256(packet[32:]).digest()==packet[:32]:
        prior=json.loads(packet[32:])
    assert prior.keys()<=specs.keys()
    hashed=Blake3(llvm)
    raw=Path("/proc/self/environ").read_bytes()
    assert raw.endswith(b"\0")
    pairs=[r.split(b"=",1) for r in raw[:-1].split(b"\0")]
    initial=dict(pairs); assert len(pairs)==len(initial)
    proc=subprocess.Popen(command,executable=real,env=initial,close_fds=False)
    seen={}; skipped={}; roles_seen=set(); adopted=0
    while True:
        for notice in sorted(state.glob("ready-*")):
            pid=notice.name[6:]
            if pid in seen or pid in skipped: continue
            assert pid.isdecimal() and notice.read_bytes()==b"complete\n"
            named=state/("actor-"+pid+".tsv"); action="full\n"
            try:
                assert 0<named.stat().st_size<48<<20
                parsed=before(named.read_text(),specs,image)
                key=parsed["role"]; assert key not in roles_seen
                old=prior.get(key)
                if kind=="allow" and parsed["allowed"] and old and old["key"]==parsed["key"]:
                    action="verify {} {} {} {}\n".format(old["output"],old["size"],old["dev"],old["ino"])
                seen[pid]=[parsed,action.split()[0]]
                roles_seen.add(key)
            except FAIL as e:
                skipped[pid]={"at":"before","failure":type(e).__name__,"message":str(e)[:240]}
            finally:
                atom(state/("answer-"+pid),action.encode())
        status=proc.poll()
        if status is not None:
            try:
                child,code=os.waitpid(-1,os.WNOHANG)
                if child: adopted+=1; continue
            except ChildProcessError: break
        time.sleep(.005)
    result={}; updated={}; commit=status==0
    for pid,(parsed,response) in seen.items():
        role=parsed["role"]
        text=(state/("actor-"+pid+".tsv")).read_text()
        brief={k:parsed[k] for k in ("key","parts","input_bytes","inputs","missed","allowed")}
        entry={**brief,"pid":pid,"response":response,"prior":prior.get(role)}
        if commit:
            try:
                nxt,actual=finish(text,parsed,response,prior.get(role),hashed,tag)
                entry.update(actual)
                if nxt: updated[role]=nxt
            except FAIL as e:
                entry["invalid_terminal"]=[type(e).__name__,str(e)[:240]]
                commit=False
        result[role]=entry
    if status==0 and len(seen)+len(skipped)!=48:
        commit=False
    if commit:
        payload=encode(updated); packet=hashlib.sha256(payload).digest()+payload
        assert len(packet)<=limit
        assert os.pwrite(memory,packet,0)==len(packet)
        os.ftruncate(memory,len(packet))
    atom(report,encode({"stage":tag,"exit":status,"commit":commit,"adopted_late_children":adopted,
                        "before_bytes":start_size,"after_bytes":os.fstat(memory).st_size,
                        "proof_refusals":skipped,"actors":result})+b"\n")
    if status: return status
    assert commit, ("source native handed no qualifying terminal original",tag,list(result.keys()),skipped)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
