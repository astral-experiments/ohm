"""Prove which native uv-cli archive was consumed, and compare its real ELF object members."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

D=Path(__file__).resolve().parent
CASES=("default","legacy","machine","human","auto","invalid","conflict")

def lib(target):
    units=[p for p in target.rglob("libuv_cli-*.rlib") if (p.parent.parent/"fingerprint/lib-uv_cli.json").is_file()]
    unit,=units
    assert unit.is_file() and not unit.is_symlink() and unit.with_suffix(".rmeta").is_file()
    return unit

def keep(unit,dest):
    dest.mkdir(mode=0o700)
    for f in (unit,unit.with_suffix(".rmeta")):
        os.link(f,dest/f.name)
    return dest/unit.name

def members(unit):
    # GNU/SysV archive table with optional LLVM/BSD length-prefixed member names.
    assert 0<unit.stat().st_size<512<<20
    result={};longs=b""
    with unit.open("rb") as f:
        assert f.read(8)==b"!<arch>\n"
        while header:=f.read(60):
            assert len(header)==60 and header[58:]==b"\x60\n"
            raw=header[:16].decode("ascii").rstrip();n=int(header[48:58]);start=f.tell();name=raw
            if raw=="//":
                assert n<4<<20;longs=f.read(n)
            elif raw.startswith("#1/"):
                k=int(raw[3:]);assert 0<k<=min(n,2048);name=f.read(k).rstrip(b"\0").decode()
            elif raw.startswith("/") and raw[1:].isdigit():
                i=int(raw[1:]);assert 0<=i<len(longs);j=longs.index(b"/\n",i);name=longs[i:j].decode()
            else:
                name=raw.removesuffix("/")
            if name.endswith(".o"):
                assert name not in result and len(result)<4096
                remaining=start+n-f.tell();assert remaining>=4
                h=hashlib.sha256();first=f.read(4);assert first==b"\x7fELF";h.update(first);remaining-=4
                while remaining:
                    buf=f.read(min(1<<20,remaining));assert buf;h.update(buf);remaining-=len(buf)
                result[name]=h.hexdigest()
            f.seek(start+n+n%2)
    assert result
    return result

def probe(e,q,unit,original,arm,state,dest):
    dest.mkdir(mode=0o700);libs=[p for p in e.TARGET.rglob("lib*") if p.suffix in (".rlib",".so") and p.is_file() and (p.parent.parent/"fingerprint").is_dir()]
    deps=q.read(original.parent.parent/"fingerprint/lib-uv_cli.json")["deps"]
    token,=[row[3].to_bytes(8,"little").hex() for row in deps if row[1]=="clap"]
    clap,=[p for p in libs if p.match("libclap-*.rlib") and (p.parent.parent/"fingerprint/lib-clap").read_text().strip()==token]
    args=[e.SDK/"bin/rustc","--edition=2024",D/"probe.rs","-C","debuginfo=0"]
    for kind,paths in (("dependency",{p.parent for p in libs}),("native",{p.parent for p in e.TARGET.rglob("*.a")})):
        for path in sorted(paths):args+=["-L",kind+"="+str(path)]
    for name,path in (("clap",clap),("uv_cli",unit)):
        for artifact in (path,path.with_suffix(".rmeta")):
            if artifact.is_file():args+=["--extern",name+"="+str(artifact)]
    exe=dest/"parser";env=e.environment();cmd=[*args,"-o",exe]
    a=subprocess.run(cmd,cwd=e.SRC,env=env,capture_output=True,timeout=120)
    def item(p):
        assert max(len(p.stdout),len(p.stderr))<=64<<10
        return {"argv":list(map(str,p.args)),"return":p.returncode,"stdout":p.stdout.decode(),"stderr":p.stderr.decode()}
    out={"arm":arm,"state":state,"compiler":e.ID[arm]["driver_sha256"],"archive":str(unit),"archive_sha256":q.sha(unit),
         "archive_bytes":unit.stat().st_size,"rmeta_sha256":q.sha(unit.with_suffix(".rmeta")),"compile":item(a)}
    if a.returncode:return out
    b=subprocess.run([exe],cwd=e.SRC,env=env,capture_output=True,timeout=45)
    out.update(execute=item(b),program_sha256=q.sha(exe),objects=members(unit))
    return out

def check_probe(row):
    assert row["compile"]["return"]==0 and row["execute"]["return"]==0 and not row["execute"]["stderr"]
    expect=["accepted","accepted",*(["UnknownArgument"]*5 if row["state"]=="A" else ["accepted"]*3+["InvalidValue","ArgumentConflict"])]
    assert row["execute"]["stdout"]=="".join(f"{name} {res}\n" for name,res in zip(CASES,expect,strict=True))
    assert row["objects"] and all(name.endswith(".o") and re.fullmatch("[0-9a-f]{64}",h) for name,h in row["objects"].items())
    assert len(row["objects"])<=4096 and 0<row["archive_bytes"]<512<<20

def compare(a,b):
    check_probe(a);check_probe(b)
    assert a["arm"]==b["arm"] and (a["state"],b["state"])==("A","B") and a["compiler"]==b["compiler"]
    assert a["archive_sha256"]!=b["archive_sha256"] and a["execute"]["stdout"]!=b["execute"]["stdout"]
    before=a["objects"];after=b["objects"];common=before.keys()&after.keys()
    return {"A_objects":len(before),"B_objects":len(after),"same_name":len(common),
            "same_name_and_content":sum(before[k]==after[k] for k in common),
            "same_content_any_name":len(set(before.values())&set(after.values()))}

