"""Authenticate six ordinary uv implementations, their two registry traits and actual macro ELF."""
from pathlib import Path
import hashlib,json
import identity_wire as wire


def object_id(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()


def confirm(parser, compiler, states, registry, macro, source, candidate):
    """`states` maps A, B and cold B to actual unmodified uv_pypi_types checked artifacts."""
    wire.bind(parser)
    assert set(states)=={"A","B","cold"} and set(source)=={"A","B"}
    version,epoch=compiler
    stamp=(version[:9].encode(),f"(Ohm metadata {epoch})".encode())
    scope=wire.case
    for phase,data in source.items():
        assert object_id(data)==scope["original_blob_"+phase],("unregistered uv source",phase)
    raw=registry.read_bytes()
    assert all(x in raw[:200] for x in stamp),"mismatched rkyv compiler"
    head,keys=wire.identity_rows(raw)
    name,_,public=wire.hdr(raw)
    assert name=="rkyv"
    paths={path:k for k,path in keys.items()}
    assert len(paths)==len(keys),"ambiguous registry paths"
    traits={name:paths[(("CrateRoot",None,0),("TypeNs","traits",0),("TypeNs",name,0))] for name in ("Archive","Deserialize")}
    identity={"sha256":wire.sha(raw),"stable_crate_id":head["stable_crate_id"],"public":public,"extra":head["extra_filename"],"traits":traits}
    proc=wire.macro_elf(macro)
    assert proc["name"]=="rkyv_derive" and all(x.decode()in proc["compiler_stamp"] for x in stamp),"mismatched proc macro"
    phases={}
    for phase,path in states.items():
        assert all(k in path.read_bytes()[:200] for k in stamp)
        phases[phase]=wire.dump(path,source["A" if phase=="A" else "B"],identity,proc,version[:9])
    a,b,c=(phases[n] for n in ("A","B","cold"))
    assert a["rmeta_sha256"]!=b["rmeta_sha256"] and a["public"]!=b["public"]==c["public"]
    assert len({p["stable_crate_id"] for p in phases.values()})==1
    slots={}
    for key,old in a["rows"].items():
        new=b["rows"][key]
        assert new==c["rows"][key],("warm/cold six-identity row",key)
        for field in ("module","members","declaring_trait"):
            assert old[field]==new[field],("different native owner/trait/member",key,field)
        for field in ("resolved_stable_crate_id","resolved_local_hash"):
            assert old["derive"][field]==new["derive"][field],("changed native macro",key,field)
        if candidate:
            assert new["slot"]==old["slot"]>=2**31 and new["full_impl_identity"]==old["full_impl_identity"],("lost derive identity",key)
        else:
            assert new["slot"]==old["slot"]+2 and new["full_impl_identity"]!=old["full_impl_identity"],("expected historical compiler displacement",key)
        slots[key]=[old["slot"],new["slot"]]
    assert len(slots)==6
    proc.pop("path")
    return {"compiler":version,"metadata_epoch":epoch,"candidate":candidate,"selected_slots":slots,
            "registry":identity,"macro":proc,"physical_evidence":phases}
