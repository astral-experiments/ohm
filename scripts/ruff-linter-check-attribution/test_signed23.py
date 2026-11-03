"""Exercise the actual receiver under isolated Python with a shadowing donor worker."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(value, why):
    if not value:
        raise ValueError(why)

def test():
    here=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);donor=base/"donor";donor.mkdir()
        (donor/"worker.py").write_text("raise RuntimeError('incorrect donor worker')\n")
        sys.path[:0]=[str(donor),str(here)]
        import signed23 as m
        archive=base/"sdk.tgz";template={}
        with tarfile.open(archive,"w:gz") as t:
            for i in range(79):
                old=f"lib/x{i}-0123456789abcdef.rlib";new=old.replace("0123456789abcdef","fedcba9876543210")
                member=tarfile.TarInfo("rust-host/std/"+new);payload=f"physical {i}".encode();member.size=len(payload);member.mode=0o644
                t.addfile(member,io.BytesIO(payload));template[old]=["rust-host/std/"+old,0o644,0,"untrusted-prior-digest"]
        prov=base/"provenance";prov.write_text('{"source":"fixture"}')
        chk=base/"checksum";chk.write_text(digest(archive)+"  fixture.tgz\n")
        assets={k:{"id":i,"name":n,"size":p.stat().st_size,"digest":"sha256:"+digest(p)} for i,(k,n,p) in
                enumerate([("archive","fixture.tgz",archive),("checksum","sha",chk),("provenance","prov",prov)],1)}
        m.BINDING={"assets":assets,"release":"tested","published_at":"test","packaging":"test","provenance":{"source":"fixture"}}
        detail=base/"detail";detail.write_text(json.dumps(dict(tag_name="tested",target_commitish="test",published_at="test",assets=list(assets.values()))))
        root=base/"private";root.mkdir()
        paths={"releases/tags/tested":detail,**{"releases/assets/"+str(i):p for i,p in enumerate([archive,chk,prov],1)}}
        def installer(out):
            return SimpleNamespace(need=require,sha=digest,ROOT=out,SDK=out/"installed",OUT=out,
                      gh=lambda key,*opts:["/bin/cat",str(paths[key])],save=lambda p,v:p.write_text(json.dumps(v)))
        m.install(installer(root),template)
        table=json.loads((root/"sdk.json").read_bytes())["members"]
        assert len(table)==79 and all(n.endswith("-fedcba9876543210.rlib") and digest(root/"installed"/n)==row[3] for n,row in table.items())
        (base/"bad").mkdir();archive.write_bytes(archive.read_bytes()+b"bad")
        try:m.install(installer(base/"bad"),template)
        except ValueError as exc:assert str(exc)=="wrong release archive" and not (base/"bad/installed").exists()
        else:raise AssertionError("accepted wrong release")
        print("all 79 modes/sizes/body digests, shadowing worker, renamed outputs and wrong-archive refusal pass")

if __name__=="__main__":test()
