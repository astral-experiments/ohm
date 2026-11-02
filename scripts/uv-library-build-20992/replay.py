"""Reopen original outcomes, native archives, instructions and all eight paired clocks."""
from pathlib import Path
from fractions import Fraction
import json
import math
import os
import re
import statistics
import struct
import sys
import tempfile
HERE=Path(__file__).resolve().parent
def main():
    root=Path(sys.argv[1]).resolve(strict=True);os.environ["OHM20992_RESULT"]=str(root)
    with tempfile.TemporaryDirectory()as tmp:
        os.environ["OHM20992_TRANSIENT"]=tmp;sys.path.insert(0,str(HERE))
        import native,evidence,worker,kernel,verify_returns
        p=worker.P;result=native.read(root/"result.json");assert result["registration"]==native.sha(HERE/"protocol.json")
        host=native.read(root/"host.json");assert host["boot"]not in native.read(HERE/"host-exclusions.json") and host["attempt"]==1
        worker.verify_openings()
        def readonly_header(data):
            h=evidence.wire.ident(data);headers=root/"native-headers"/active_driver
            raw=(headers/(h+".zls-root")).read_bytes();r=native.read(headers/(h+".json"));assert r["raw_rmeta"]==h and r["exit"]==0 and r["native_driver"]==active_driver and r["stdout"]==evidence.wire.ident(raw)and r["argv"][1]=="-Zls=root";return raw
        evidence.meta.native_header=readonly_header
        verify_returns.reopen()
        for role in ("parent","candidate"):
            active_driver=native.read(root/"sdk-identities.json")[role]["driver"]
            for state in ("A","B"):
                for hold in range(1,9):
                    w=worker.anchors(role,hold);z=w/("anchor-"+state);A=native.read(z/"native-products.json");links=native.read(z/"linked.json");native.linked.check_probe(links)
                    assert native.read(z/"hostile-native-mutants.json")==evidence.hostile(A)
                    assert native.read(z/"native-metadata.json")=={n:evidence.wire.ident(readonly_header(evidence.meta.metadata_member(evidence.unpack(a))[1]))for n,a in A["archives"].items()}
                    pure=native.read(w/(state+"-kernel")/"process/observed-rustcs.json")
                    for suffix in ("-kernel","-verbose"):
                        ck=w/(state+suffix);k=native.read(ck/"process/observed-rustcs.json");assert k["kernel_sha"]==native.sha(ck/"process/kernel-events.json")
                        ev=kernel.EVENTS["decode"](native.read(ck/"process/kernel-events.json"));assert ev["root"]==k["root"] and ev["exits"][k["root"]]==0
                        for n,v in k["targets"].items():
                            assert len([im for im in ev["images"]if im["pid"]==v["pid"] and im.get("argv")==v["argv"] and im["file"]==v["inode"]])==1 and ev["exits"][v["pid"]]==0
                        assert kernel.match(pure,k);obs=native.read(ck/"native-products.json");assert evidence.compare(A,obs,state)==native.read(ck/"all-equivalent.json")
                    if hold > 1:
                        first=native.read(worker.anchors(role,1)/("anchor-"+state)/"native-products.json")
                        assert evidence.compare(first,A,state,True)==native.read(w/(state+"-across-independent.json"))
        ratios=[];roles={"C":"candidate","P":"parent"}
        for h,orders in enumerate(p["orders"],start=1):
            for i,order in enumerate(orders,start=1):
                k=(h-1)*4+i;pair={}
                for pos,ch in enumerate(order,start=1):
                    role=roles[ch];w=worker.anchors(role,k);anchor=native.read(w/"anchor-B/native-products.json")
                    labels=kernel.vectors(native.read(w/"B-kernel/process/observed-rustcs.json"))
                    for mode in ("ordinary","whole-instructions","rustcs"):
                        d=root/f"pair-{k:02d}"/f"{pos}-{role}"/mode;co=d/"native";a=native.read(d/"accepted.json");assert a==result["rows"][str(k)][role][mode] and (a["number"],a["position"],a["hold"],a["role"],a["mode"])==(k,pos,h,role,mode)
                        got=native.read(d/"native-products.json");assert a["outputs"]==native.sha(d/"native-products.json") and a["observed"]==native.sha(d/"all-outputs.json") and a["seed"]==native.sha(w/"seed.json") and native.read(d/"all-outputs.json")==evidence.compare(anchor,got,"B")
                        score=a["sample"]
                        if mode=="ordinary":
                            rec=native.read(co/"record.json");assert rec["argv"]==kernel.command() and rec["exit"]==0 and rec["start_monotonic_ns"]<rec["end_monotonic_ns"]and rec["wall_ns"]==rec["end_monotonic_ns"]-rec["start_monotonic_ns"] and all(score[n]==v for n,v in rec.items())
                            assert rec["stdout"]==native.sha(co/"stdout")and rec["stderr"]==native.sha(co/"stderr");m,=re.findall(r"Finished .*? in ([0-9.]+)s",(co/"stderr").read_text());assert float(m)==score["cargo_finished_seconds"]
                            links=native.read(d/"linked.json");native.linked.check_probe(links);assert native.linked.compare(native.read(w/"anchor-A/linked.json"),links);pair[role]=rec["wall_ns"]
                        elif mode=="whole-instructions":
                            assert score==worker.hardware.whole_record(native.read(co/"instructions.json"))
                            cmd=native.read(co/"record.json");assert cmd["argv"][2:]==kernel.command() and cmd["exit"]==0
                        else:
                            assert score==native.read(co/"per-rustc.json")["targets"]and score.keys()==labels.keys()
                            kdata=native.read(co/"kernel-events.json");tree=kernel.EVENTS["decode"](kdata)
                            for name,v in score.items():
                                raw=struct.unpack("=4Q",bytes.fromhex(v["raw_hex"]));assert raw==(v["instructions"],v["time_enabled_ns"],v["time_running_ns"],v["event_id"]) and raw[0]>0 and raw[1]==raw[2]>0
                                assert v["argv"]==labels[name] and any(x.get("argv")==v["argv"]and x["pid"]==v["pid"]and x["file"]==v["file"]for x in tree["images"])and tree["exits"][v["pid"]]==0
                ratios.append(Fraction(pair["candidate"],pair["parent"]))
        med=[statistics.median(ratios[n:n+4])for n in (0,4)];k=sum(r<Fraction(11,10)for r in ratios);p=sum(math.comb(8,i)for i in range(k,9))/256
        assert result["candidate_over_parent"]==[float(r)for r in ratios]and all(abs(float(a)-b)<1e-15 for a,b in zip(med,result["hold_medians"],strict=True))and result["strictly_below_1p10"]==k and result["sign_one_sided"]==p and result["admitted"]==(all(r<Fraction(21,20)for r in med)and k>=7)
        return {"admitted":result["admitted"],"counts":len(ratios),"median_ratios":list(map(float,med)),"below_1p10":k,"one_sided_sign":p,"source":"original blocking wall, complete archives and two independently calibrated instruction methods"}
if __name__=="__main__":print(json.dumps(main(),sort_keys=True))

