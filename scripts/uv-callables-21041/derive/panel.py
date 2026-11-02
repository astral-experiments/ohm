"""Authenticate all original metadata paths and the six real generated impls before first-edit counters."""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import gzip,json,shutil,sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import identity_wire as wire
from migration_keys import diff,accept
from native_units import NativeUnits
from six import confirm,object_id

PHASES={"ordinary-A":"A","warm-B":"B","cold-B":"cold"}
SOURCES=("10d56274a98801b5ef8f80aab734e835749458e1","ac67101cb973e35ce8ff044cc8014c2c76bab69e")
SCHEMAS=(3,43319)
EDIT=Path("crates/uv-pypi-types/src/simple_json.rs")
def digest(b):return sha256(b).hexdigest()
def encode(x):return json.dumps(x,sort_keys=True,separators=(",",":")).encode()
def read(p):return json.loads(p.read_bytes())
def store(output,data):
    if output.is_file():assert output.read_bytes()==data,("existing unrelated bytes",output.name)
    else:
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("xb") as f:f.write(data)
def write(path,value):
    store(path,encode(value)+b"\n")
def packed(path,value):
    store(path,gzip.compress(encode(value),compresslevel=4,mtime=0))
def capture(target,sdk,src,visit,material,role,out,tmp):
    if visit.name not in PHASES:return
    source=(src/EDIT).read_bytes()
    phase=PHASES[visit.name];rev="A" if phase=="A" else "B"
    assert object_id(source)==wire.case["original_blob_"+rev],"unexpected ordinary source"
    vault=tmp/"derive-source-vault";vault.mkdir(exist_ok=True)
    store(out/"derive-evidence"/("source-"+rev+".rs"),source)
    files={};length=0
    for base,root,globs in (("target",target,("*.rmeta","*.so")),("sysroot",sdk/"lib/rustlib/x86_64-unknown-linux-gnu/lib",("*.rmeta",))):
        for suffix in globs:
            for f in sorted(root.rglob(suffix)):
                assert f.resolve(strict=True)==f and f.is_relative_to(root) and f.is_file(),("unregistered path",f)
                b=f.read_bytes();n=len(b);assert 0<n<192<<20,("unbounded native library",f,n)
                key=digest(b);p=vault/key
                if not p.is_file():store(p,b)
                else:assert p.stat().st_size==n
                rel=str(f.relative_to(root));files[base+"/"+rel]=[key,n];length+=n
    assert 37<len(files)<2200 and length<5<<30
    for label,rel in material["relative_paths"].items():
        size,sha=material["raw"][label];assert files["target/"+rel]==[sha,size]
    ledger={"role":role,"phase":phase,"actual_source_blob":object_id(source),"actual_products_sha256":digest((visit/"products.json").read_bytes()),"members":files}
    packed(visit/"derive-native-libraries.json.gz",ledger)

def enroll_ledger(q,phase,role,vault):
    visit=q/phase;ledger=json.loads(gzip.decompress((visit/"derive-native-libraries.json.gz").read_bytes()))
    prod=read(visit/"products.json");assert ledger["role"]==role and ledger["phase"]==PHASES[phase]
    assert digest((visit/"products.json").read_bytes())==ledger["actual_products_sha256"] and len(prod["raw"])==37
    assert object_id((q.parents[1]/"derive-evidence"/("source-"+("A" if phase=="ordinary-A" else "B")+".rs")).read_bytes())==ledger["actual_source_blob"]
    indexed=defaultdict(set)
    for k,(sha,n) in ledger["members"].items():
        assert len(sha)==64 and n>0 and k.split("/",1)[0] in ("target","sysroot") and ".." not in Path(k).parts
        indexed[Path(k).name].add(vault/sha)
    workspace={}
    for label,rel in prod["relative_paths"].items():
        sha,n=ledger["members"]["target/"+rel];assert prod["raw"][label]==[n,sha]
        workspace[label]=vault/sha
    return ledger,workspace,NativeUnits((),None,{},indexed)
def actual_external(roster,crate,consumer):
    cmd,=[v for v in roster if v[v.index("--crate-name")+1]==consumer]
    externs=[value.split("=",1)[1]for pos,value in enumerate(cmd)if pos>0 and cmd[pos-1]=="--extern" and value.startswith(crate+"=")]
    path,=externs;return Path(path).name

def verify_hold(out,tmp,hold,roles,parse,independent=False):
    wire.bind(parse)
    panel=out/"uv-client";evidence=out/"derive-evidence";vault=tmp/"derive-source-vault"
    qs=[panel/f"hold-{hold}-{r}"for r in roles];stash=out/"rmeta-by-content"
    reopened=None
    if independent:
        reopened=TemporaryDirectory(prefix="derive-original-replay-",dir=tmp)
        vault=Path(reopened.name)
        saved=read(evidence/f"hold-{hold}-retained.json")
        for sha,n in saved.items():
            assert len(sha)==64 and set(sha)<=set("0123456789abcdef") and type(n)is int and 0<n<192<<20
            packed_file=(evidence/"dependencies"/(sha+".gz"))
            source_bytes=gzip.decompress(packed_file.read_bytes())
            assert digest(source_bytes)==sha and len(source_bytes)==n
            store(vault/sha,source_bytes)
    def selected_files(ledger,workspace,roster):
        reg=actual_external(roster,"rkyv","uv_pypi_types")
        entries=[(k,val)for k,val in ledger["members"].items() if Path(k).name==reg]
        assert entries and len(set(val[0]for k,val in entries))==1
        registry=vault/entries[0][1][0]
        macros={x[0]for k,x in ledger["members"].items()if k.startswith("target/") and Path(k).name.startswith("librkyv_derive-") and k.endswith(".so")}
        assert len(macros)==1,"expected one installed rkyv_derive ELF"
        macro=vault/next(iter(macros))
        return workspace["uv_pypi_types@check"],registry,macro
    receipts={};retained=set();seen=[{},{}];deps=[{},{}]
    roster=[read(q/"typed-B/roster.json")["commands"]for q in qs]
    for phase,identifier in PHASES.items():
        left,right=[enroll_ledger(q,phase,role,vault)for q,role in zip(qs,roles,strict=True)]
        assert left[1].keys()==right[1].keys() and len(left[1])==37
        states=(left,right)
        for i,(ledger,workspace,bank)in enumerate(states):
            file,registry,macro=selected_files(ledger,workspace,roster[i])
            seen[i][identifier]=file;deps[i][identifier]=(registry,macro)
            retained.update((registry,macro))
        pairs={}
        for label in sorted(left[1]):
            data=[v[1][label].read_bytes()for v in states]
            for blob,i,(ledger,files,bank) in zip(data,range(2),states,strict=True):
                assert digest(blob)==files[label].name and SOURCES[i][:9].encode()in blob[:220] and ("(Ohm metadata "+str(SCHEMAS[i])+")").encode()in blob[:220]
            obs=None
            try:
                obs=diff(*data,[s[2]for s in states]);summary=accept(obs)
            except (ValueError,AssertionError,KeyError,IndexError) as exc:
                refusal={"unit":label,"phase":identifier,"error":type(exc).__name__,"detail":str(exc)[:1200],
                         "workspace_raw":[s[1][label].name for s in states],"native_comparison":obs}
                packed(evidence/f"hold-{hold}-{identifier}-refused.json.gz",refusal)
                for s in states:
                    for orig in s[2].inspected:
                        body=orig.read_bytes();assert digest(body)==orig.name
                        dst=evidence/"dependencies"/(orig.name+".gz")
                        if not dst.exists():store(dst,gzip.compress(body,compresslevel=2,mtime=0))
                raise
            assert obs["crate"]==label.split("@")[0]
            pairs[label]={**summary,"raw":[s[1][label].name for s in states],"native":obs}
            retained.update(s[1][label]for s in states)
        refs=[]
        for ledger,workspace,bank in states:
            retained.update(bank.inspected)
            refs.append([[key,value] for key,value in sorted(bank.used.items(),key=lambda x:repr(x[0]))])
        NativeUnits.declarations.cache_clear()
        destination=evidence/f"hold-{hold}-{identifier}.json.gz"
        packed(destination,{"units":pairs,"external_native":refs})
        receipts[identifier]={"sha256":digest(destination.read_bytes()),**{key:sum(p[key]for p in pairs.values())for key in ("definitions","common","migrated_paths","typed_impl_owners","maximal_roots")}}
    source={k:(evidence/("source-"+k+".rs")).read_bytes()for k in ("A","B")}
    for i,role in enumerate(roles):
        assert len(set(deps[i].values()))==1,"rkyv dependency bytes changed across the same compiler's A, warm B or clean B"
        reg,mac=next(iter(deps[i].values()))
        obs=confirm(parse,(SOURCES[i],SCHEMAS[i]),seen[i],reg,mac,source,i==1)
        dest=evidence/f"hold-{hold}-{role}-six.json.gz";packed(dest,obs);receipts[role]={"six":digest(dest.read_bytes()),"selected":len(obs["selected_slots"])}
    kept={};size=0
    for f in sorted(retained):
        assert len(f.name)==64
        b=f.read_bytes();assert digest(b)==f.name
        kept[f.name]=len(b);size+=len(b)
        # The original product verifier already keeps the uncompressed equivalent under its digest.
        product=stash/(f.name+".gz");dest=evidence/"dependencies"/(f.name+".gz")
        if product.exists():
            assert gzip.decompress(product.read_bytes())==b
            if not dest.exists():store(dest,product.read_bytes())
        elif not dest.exists():store(dest,gzip.compress(b,compresslevel=2,mtime=0))
        else:assert gzip.decompress(dest.read_bytes())==b
    assert len(kept)<450 and size<1024<<20,("unexpected evidence dependency footprint",len(kept),size)
    write(evidence/f"hold-{hold}-retained.json",kept);write(evidence/f"hold-{hold}-passed.json",receipts)
    if reopened is not None:reopened.cleanup()
    return receipts
