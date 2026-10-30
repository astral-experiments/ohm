"""Independently reopen a rejected Apple acquisition, excluding every earlier clock."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from macho import TOKEN, checked_slots
from project import Raw, authenticated_image, kernel, sha

def executable(raw, location):
    body = raw.unpack(location+"/stdout.gz")
    lines = [json.loads(row) for row in body.splitlines()]
    assert lines[-1] == {"reason":"build-finished","success":True}
    exe, = [r["executable"] for r in lines if r.get("executable") and
            r["target"]["name"]=="ruff_python_ast" and r["profile"]["test"]]
    return exe, sha(body)

def readback(raw_path, source):
    raw = Raw(raw_path)
    assert raw.digest == source["zip_sha256"] and len(raw.files) == source["zip_entries"]
    assert Path(raw_path).stat().st_size == source["zip_bytes"] and source["eligible_pairs"]==0
    assert "test-screen/result.json" not in raw.files and "test-confirm/result.json" not in raw.files
    clocks=[f for f in raw.files if f.startswith("test-screen/pair-") and f.endswith("/time.txt")]
    assert len(clocks)==source["recorded_arm_commands_with_clocks"]
    obs=kernel(raw)
    if source["run"] == 41052488154:
        path="test-screen/native-before/P/empty-old/clean"
        executable(raw,path)
        listed=raw.unpack(path+"/test-list.gz").decode().splitlines()
        assert len(listed)==source["old_inventory"]==53 and all(t.endswith(": test") for t in listed)
        assert b"test nodes::tests::size ... ok" in raw.unpack(path+"/size.gz")
        events=json.loads(raw.unpack(path+"/exec.json.gz"))
        compilers=[r for r in events if r["path"].endswith("/native/bin/rustc") and "--crate-name" in r["argv"]
                   and r["argv"][r["argv"].index("--crate-name")+1]!="___"]
        assert len(compilers)==source["old_rustc"]==36 and path+"/test-suite.gz" not in raw.files
    elif source["run"] == 41053629169:
        for state,expected in source["by_state"].items():
            images=[authenticated_image(raw,f"test-screen/native-before/{r}/empty-{state}/clean",obs) for r in "PC"]
            (a,ca,ma),(b,cb,mb)=images
            assert sha(a)==expected["P"] and sha(b)==expected["C"] and ca==cb
            assert sha(ca)==expected["canonically_equal_image_sha256"]
            assert len(a)==len(b)==expected["bytes"] and ma["slots"]==mb["slots"]
            changed={i for i,(x,y) in enumerate(zip(a,b)) if x!=y}
            slots={i for start,stop in ma["slots"] for i in range(start,stop)}
            pages,span,limit,hashstart=ma["layout"]["page"]
            changed_pages={p//span for p in changed&slots}
            signed={i for p in changed_pages for i in range(hashstart+p*32, hashstart+(p+1)*32)}
            assert changed<=slots|signed and len(changed)==expected["different_bytes"]
            assert len(changed&slots)==expected["different_debug_path_bytes"] and len(changed&signed)==expected["different_signature_bytes"]
            assert pages==expected["signature_pages"] and sorted(changed_pages)==expected["original_pages_changed"]
    else:
        assert source["run"]==41055128844 and len(source["by_phase"])==4
        for label,out in source["by_phase"].items():
            ref=f"test-screen/native-before/P/empty-{out['state']}/clean"
            event="test-screen/pair-01/P/"+label
            assert not any(p.startswith("test-screen/pair-01/C/") for p in raw.files)
            clean,_,meta=authenticated_image(raw,ref,obs)
            clean_receipt=raw.obj(ref+"/verified.json")
            observed=raw.obj(event+"/verified.json")
            src,_=executable(raw,ref);dst,stream=executable(raw,event)
            orig,=TOKEN.finditer(src.encode());new,=TOKEN.finditer(dst.encode())
            assert orig[1]==new[1] and orig[2]!=new[2] and src.encode().replace(b"/v2-"+orig[2]+b"/",b"/v2-"+new[2]+b"/")==dst.encode()
            assert stream==observed["streams"]["stdout"]==out["observed_cargo_stdout"]
            assert clean_receipt["streams"]["native_events"]==out["native_clean_linker_stream"] and obs["sha"]==out["physical_stock_ld"]
            assert all(clean_receipt["product"][k]==observed["product"][k] for k in ("tests","verdicts","text"))
            changed=bytearray(clean)
            for start,stop in meta["slots"]:
                assert clean[start:stop]==orig[2]
                changed[start:stop]=new[2]
            reconstructed=checked_slots(changed,meta["layout"],replace=True)
            checked_slots(reconstructed,meta["layout"])
            assert observed["product"]["raw"]==sha(reconstructed)==out["reconstructed"]==out["observed_full_macho"]
            assert sha(clean)==out["clean"] and len(clean)==len(reconstructed)==out["size"]
            assert sum(x!=y for x,y in zip(clean,reconstructed))==out["differing_bytes"]
    return {"run":source["run"],"eligible_pairs":0,"sha256":raw.digest,"entries":len(raw.files)}

if __name__=="__main__":
    if not __debug__: raise SystemExit("Use Python without -O.")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args=parser.parse_args()
    src,=[v for v in json.loads((HERE/"excluded.json").read_text()) if v["zip_sha256"]==sha(args.archive.read_bytes())]
    print(json.dumps(readback(args.archive,src),indent=2,sort_keys=True))
