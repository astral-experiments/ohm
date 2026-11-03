"""Read each compiler's own native metadata before comparing products across compiler versions."""
from common21577 import *
from source_intake import ROLES

def logical_path(name,root_name):
    if name.startswith("debug/build/"):
        return name
    pattern=r"debug/incremental/([a-z0-9_]+)-[a-z0-9]+/session-crate-hash-[a-z0-9]+/([a-z-]+\.rmeta)"
    match=re.fullmatch(pattern,name)
    assert match and root_name.rsplit("-",1)[0]==match[1],(name,root_name)
    return f"debug/incremental/{match[1]}/{match[2]}"

def interpret(raw,selected):
    lines=raw.decode().splitlines()
    assert lines[0]=="Crate info:" and lines[1].startswith("name ")
    name=lines[1].removeprefix("name ")
    hashes=re.fullmatch(r"private hash ([0-9a-f]{32}) stable_crate_id StableCrateId\(([0-9]+)\)",lines[2])
    pub=re.fullmatch(r"public_hash ([0-9a-f]{32})",lines[3])
    assert hashes and pub and lines[-2]=="Public hash: "+pub[1] and lines[-1]==""
    start=lines.index("=External Dependencies=");end=lines.index("")
    assert 4<start<end and all(t in lines for t in ("=Lang items=","=Lib features=","=Items=","=Target modifiers="))
    sysroot={}
    for path in selected["full_members"]:
        match=re.fullmatch(r"lib/rustlib/x86_64-unknown-linux-gnu/lib/lib([a-zA-Z0-9_]+)-([0-9a-f]{16})\.(?:rmeta|rlib)",path)
        if match:sysroot[match[1]+"-"+match[2]]=match[1]
    edges=[]
    for i,line in enumerate(lines[start+1:end],1):
        m=re.fullmatch(r"([0-9]+) (\S+) hash ([0-9a-f]{32}) host_hash (None|Some\([^)]+\)) kind (.+)",line)
        assert m and int(m[1])==i,(i,line)
        # Only SDK files verified in this physical compiler may use different sysroot filenames.
        artifact=["sysroot",sysroot[m[2]]]if m[2]in sysroot else ["cargo",m[2]]
        edges.append({"artifact":m[2],"identity":artifact,"hash":m[3],"host_hash":m[4],"kind":m[5]})
    # Compare all root flags, every external order/kind/visibility, and the native reader's
    # complete lang-items, features, module-items/visibility and target-modifier text.
    shape=[name,lines[4:start],[[r["identity"],r["host_hash"]!="None",r["kind"]] for r in edges],lines[end:-2]]
    digest=hashlib.sha256(json.dumps(shape,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return {"name":name,"private":hashes[1],"public":pub[1],"stable":int(hashes[2]),"edges":edges,"shape":digest}

def observe(selected,opening,store,dest):
    dest.mkdir()
    inputs={d for phase in "AB" for _,d in opening[phase]["rmeta"].values()}
    for digest in sorted(inputs):
        raw=gzip.decompress((store/(digest+".gz")).read_bytes())
        assert hashlib.sha256(raw).hexdigest()==digest
        with tempfile.TemporaryDirectory(dir=ROOT/"bank") as tmp:
            meta=Path(tmp)/"input.rmeta";meta.write_bytes(raw)
            p=subprocess.run([SDK/"bin/rustc","-Zls=all",meta],capture_output=True,env=ENV)
            assert p.returncode==0 and not p.stderr and p.stdout,p.stderr[-900:]
        interpret(p.stdout,selected)
        (dest/(digest+".gz")).write_bytes(gzip.compress(p.stdout,mtime=0))

def joint(opened,selected,read_blob,read_view):
    assert set(opened)==set(selected)==set(ROLES)
    records={}
    for role in ROLES:
        v=opened[role];known={};model={};raw_phases={}
        for phase in "AB":
            sf=v[phase];assert [len(sf[k])for k in ("rmeta","sidecars","workspace")]==[39,30,4]
            assert all(sf["rmeta"][p]==row for p,row in sf["workspace"].items())
            rows={};logical={};cargo={}
            for name,(n,digest) in sf["rmeta"].items():
                if digest not in known:
                    raw=gzip.decompress(read_blob(digest+".gz"))
                    assert len(raw)==n and hashlib.sha256(raw).hexdigest()==digest
                    ls=gzip.decompress(read_view(role,digest))
                    known[digest]=interpret(ls,selected[role])
                    known[digest]["encoded_bytes"]=len(raw)
                rec=known[digest];identity=logical_path(name,rec["name"])
                assert rec["encoded_bytes"]==n
                assert identity not in rows
                logical[name]=identity;rows[identity]=rec["shape"]
                if name.startswith("debug/build/"):
                    assert rec["name"] not in cargo;cargo[rec["name"]]=rec
            sidecars={}
            for path,(n,digest)in sf["sidecars"].items():
                raw=read_blob(digest+".public-api-hash");assert len(raw)==n and hashlib.sha256(raw).hexdigest()==digest
                fp=json.loads(raw);assert set(fp)=={"version","value"} and fp["version"]==1
                prefix=path.split("/fingerprint/");assert len(prefix)==2
                matched,=[v for k,v in sf["rmeta"].items() if k.startswith(prefix[0]+"/out/")]
                own=known[matched[1]]
                assert fp["value"]==own["public"]
                sidecars[path]=own["name"]
            # Every dependency that also emitted a regular Cargo metadata product on this edit
            # must name that product and use its actual public hash.
            for rec in cargo.values():
                for edge in rec["edges"]:
                    if edge["artifact"]in cargo:assert edge["hash"]==cargo[edge["artifact"]]["public"]
            model[phase]={"metadata_shapes":rows,"workspace":sorted(logical[p] for p in sf["workspace"]),"sidecar_owners":sidecars}
            raw_phases[phase]={"rmeta":{logical[p]:v for p,v in sf["rmeta"].items()},"sidecars":sf["sidecars"],
                "public":{n:r["public"] for n,r in cargo.items()},"stable_crate_ids":{n:r["stable"]for n,r in cargo.items()}}
        model["forms"]=v["forms"]
        for ex in v["externs"].values():
            for item in ex.values():assert known[item["blob"][1]]["encoded_bytes"]==item["blob"][0]
        model["externs"]={n:{name:[p["path"],known[p["blob"][1]]["name"],known[p["blob"][1]]["shape"]] for name,p in ex.items()}for n,ex in v["externs"].items()}
        records[role]={"model":model,"raw":raw_phases,"version":selected[role]["native_banners"]["rustc"].splitlines()[0]}
    return records

def require_equal(records):
    assert set(records)==set(ROLES)
    for role in ROLES[1:]:
        assert records["S"]["model"]==records[role]["model"],("native interface, kernel argv or direct extern",role)
        if records["S"]["version"]==records[role]["version"]:
            assert records["S"]["raw"]==records[role]["raw"],("identical compiler version but different raw products",role)
        else:
            for phase in "AB":
                units=records["S"]["raw"][phase]["stable_crate_ids"];alt=records[role]["raw"][phase]["stable_crate_ids"]
                assert set(units)==set(alt) and all(units[n]!=alt[n]for n in units),("compiler version did not change each StableCrateId",role,phase)

