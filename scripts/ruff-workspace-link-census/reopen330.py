"""Check the source-matched Cargo pair and each real native verdict from its original acquisition."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import traced


def verify(path,digest):
    with path.open("rb") as f:assert hashlib.file_digest(f,"sha256").hexdigest()==digest
    commits={"parent":"2554a1dfaf22474b360a4298883acf41f82bd78f","child":"8269d772aa1ef02e5efaa331dfb40eb55d71f719"}
    bins={"parent":"39884e04e748b26929601ff217139e8a77f296f7409d52a4303e7aadf0fe8ff7","child":"3e6948caba617c5f776641df2ade87fe772d0b656a53b538cd93b63351c56c53"}
    cargo=["cargo","+ohm"]
    constructors=cargo+["test","-p","ruff_text_size","--test","constructors","--features","get-size,schemars,serde","--no-run","--locked","--offline","-j8","--message-format=json"]
    program=cargo+["build","--locked","--offline","-j8","--message-format=json"]
    cases={"train":17,"repeat":17,"shadow":29,"malformed":None,"repair":41,"remove-early":17,"missing":None}
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        names=z.namelist();assert len(set(names))==len(names) and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
        n,=[n for n in names if n.endswith("bisect-complete.json")]
        base=n.removesuffix("bisect-complete.json")
        def rd(k):return json.loads(z.read(base+k))
        meta=rd("identity.json");author=rd("bisect-complete.json");assert meta["ruff"]==author["source"] and meta["lock"]==author["lock"] and len(meta["sdk"])==79
        out={"source":author["source"],"lock":author["lock"],"run":meta["run"],"head":meta["sha"],"boot":meta["boot"],"archive_sha256":digest,"roles":{}}
        for role in ("parent","child"):
            orig=rd(role+"-artifact.json");assert orig["cargo"][:2]==[commits[role],bins[role]]
            assert commits[role].encode() in z.read(base+role+"/cargo.version")
            ctor=rd(role+"-constructor.json");assert ctor["job"] in (124570376741,124603612571) and ctor["run"]==orig["run"]
            values={}
            phases=["cold","repeat1","repeat2"]+["provider-"+m+suffix for m in cases for suffix in (("",) if m in ("train","repeat") else ("","-empty"))]
            assert len(phases)==15
            for phase in phases:
                root=role+"/"+phase
                cmd=rd(root+"/command.json")
                is_native=phase.startswith("provider-")
                assert cmd["argv"]==(program if is_native else constructors)
                rows=[json.loads(l) for l in z.read(base+root+"/stdout.jsonl").splitlines()]
                assert rows[-1]=={"reason":"build-finished","success":cmd["exit"]==0}
                arts=[a for a in rows if a["reason"]=="compiler-artifact"]
                native=traced(z,base,root)
                detail=rd(root+"/result.json")
                assert (detail["exit"],detail["typed"],detail["dirty"],detail["wild"])==(cmd["exit"],len(arts),[a["target"]["name"] for a in arts if not a["fresh"]],len(native["links"]))
                assert Counter((s[1],s[2]) for s in native["owners"].values())==Counter(tuple(t) for t in detail["rustc"])
                obs=None;diagnostics=[]
                if cmd["exit"]==0:
                    txt=z.read(base+root+"/native.stdout").decode();assert txt==detail["native"] and len(detail["elf"])==64
                    if is_native:obs=int(txt.strip())
                    else:assert "test main ... ok" in txt and "1 passed; 0 failed" in txt;obs="main passed"
                else:
                    assert cmd["exit"]==101 and not any(a["target"]["name"]=="probe" for a in arts)
                    for msg in rows:
                        if msg["reason"]!="compiler-message":continue
                        data=msg["message"]; all_text=(data.get("rendered") or "")+" "+" ".join(str(v) for v in data.get("children",[]))
                        if "linking with" in all_text or "linker" in all_text.lower():
                            diagnostics.append(hashlib.sha256(all_text.encode()).hexdigest())
                    assert diagnostics and native["links"],(role,phase)
                if phase.endswith("-empty"):
                    expected=cases[phase.removeprefix("provider-").removesuffix("-empty")]
                    assert obs==expected and cmd["exit"]==(101 if expected is None else 0)
                values[phase]={"exit":cmd["exit"],"value":obs,"elf":detail.get("elf"),"typed":len(arts),"dirty":len(detail["dirty"]),"rustc":detail["rustc"],"wild":len(native["links"]),"link_diagnostic_sha256":diagnostics}
            assert values["provider-train"]["value"]==values["provider-repeat"]["value"]==17
            mask={p:v for p,v in cases.items() if p not in ("train","repeat")}
            contrasts={p:{"equal_verdict":(values["provider-"+p]["value"],values["provider-"+p]["exit"])==(values["provider-"+p+"-empty"]["value"],values["provider-"+p+"-empty"]["exit"]),
                         "raw_elf_equal":values["provider-"+p]["elf"]==values["provider-"+p+"-empty"]["elf"] if v is not None and values["provider-"+p]["elf"] is not None else None} for p,v in mask.items()}
            reasons={}
            for ph in ("repeat1","repeat2"):
                for line in z.read(base+role+"/"+ph+"/stderr").decode().splitlines():
                    if 'target="constructors"' in line and " dirty:" in line:reasons[ph]=line.split(" dirty: ",1)[1]
            source=z.read(base+role+"/provider-source/build.rs");assert b"cargo:rerun-if-changed=build.rs" in source and b'rustc-link-search' in source and b'["early","late"]' in source
            marked=rd(role+"/marked-deps.json"); assert len(marked)==1 and all("compact_str" in n and body["markers"]==["ohm-recheck-dependent-links"] for n,body in marked.items())
            out["roles"][role]={"cargo":bins[role],"commit":commits[role],"marked_depfiles":marked,"constructors_reason":reasons,"constructors":{n:values[n] for n in ("cold","repeat1","repeat2")},"provider_contrasts":contrasts,"provider":{k:v for k,v in values.items() if k.startswith("provider-")}}
        cs=[r["constructors"][p]["elf"] for r in out["roles"].values() for p in ("cold","repeat1","repeat2")]
        assert len(set(cs))==1 and out["roles"]["child"]["marked_depfiles"]==out["roles"]["parent"]["marked_depfiles"]
        for p in ("repeat1","repeat2"):
            assert out["roles"]["child"]["constructors"][p]["rustc"]==[["constructors",True]] and out["roles"]["child"]["constructors"][p]["wild"]==1
            assert out["roles"]["parent"]["constructors"][p]["rustc"]==[] and out["roles"]["parent"]["constructors"][p]["wild"]==0
        for key,val in out["roles"]["child"]["provider_contrasts"].items():assert val["equal_verdict"] and val["raw_elf_equal"] is not False
        assert {p for p,v in out["roles"]["parent"]["provider_contrasts"].items() if not v["equal_verdict"]}=={"shadow","malformed","repair","missing"}
    return out


if __name__=="__main__":
    print(json.dumps(verify(Path(sys.argv[1]),sys.argv[2]),indent=2,sort_keys=True))
