"""Recompute all projected comparisons from the original integer measurements."""
from fractions import Fraction
from pathlib import Path
from statistics import median
import copy
import hashlib
import json


def calculate(score, registration):
    union={"feature_B":"B","auxiliary_C":"C","rename_D":"D","production_B_plus_D":"BD","entire_B_plus_C_plus_D":"BCD"}
    zones={"B":"feature_B","D":"rename_D"}
    presel=registration["confirmatory_per_pid_endpoints"]
    six={n for s,n in presel}
    assert len(six)==6 and len(presel)==12 and set(map(tuple,presel))=={(s,n) for s in "BD" for n in six}
    raw=score["per_pair_raw"]
    assert len(raw)==8 and len(score["unique_genuine_cold_kernel_digests"])==16
    for pair in raw:
        assert set(pair)=={"P","T"}
        for arm in pair.values():
            assert set(arm)==set("BCD") and all(set(v["scoped"])==six for v in arm.values())
            assert all(type(n)is int and n>0 for v in arm.values() for n in (v["wall"],v["whole"],*v["scoped"].values()))
    out={}
    for edit,states in union.items():
        out[edit]={}
        for metric in ("wall","whole","sum_six",*sorted(six)):
            def observation(arm):
                values=[arm[s] for s in states]
                if metric in six:return sum(v["scoped"][metric] for v in values)
                if metric=="sum_six":return sum(sum(v["scoped"].values()) for v in values)
                return sum(v[metric] for v in values)
            series=[[observation(pair[k]) for k in ("P","T")] for pair in raw]
            ratios=[Fraction(a,b) for a,b in series]
            thresh=Fraction(5,4) if metric in six else Fraction(2)
            holds=[median(ratios[:4]),median(ratios[4:])]
            count=sum(v>thresh for v in ratios)
            passes=count==8 and all(v>thresh for v in holds)
            x=score["endpoints"][edit][metric]
            assert series==x["raw_control_treatment"] and list(map(str,ratios))==x["paired_ratios"]
            assert str(median(ratios))==x["median"] and list(map(str,holds))==x["four_pair_hold_medians"]
            assert count==x["above_bar"] and str(thresh)==x["strict_bar"] and passes==x["eight_of_eight_and_both_holds"]
            out[edit][metric]={"raw_control_treatment":series,"median_ratio":str(median(ratios)),"median_factor":float(median(ratios)),
                               "first_hold_ratio":str(holds[0]),"second_hold_ratio":str(holds[1]),"eight_strictly_over_bar":passes,
                               "count_strictly_over_bar":count,"strict_bar":str(thresh)}
    return {"45_verified":sum(map(len,out.values()))==45,"per_pid_words":len(raw)*2*3*len(six),
            "endpoints":out,"preselected":{s+"_"+n:out[zones[s]][n] for s,n in presel}}


if __name__=="__main__":
    base=Path(__file__).resolve().parent
    orig=base.parents[1]/"independent-instructions-22/run-41564083893/native-and-score.json"
    source=json.loads(orig.read_bytes())["original"]
    reg=json.loads((base/"coordinator/scripts/uv-check-22536/registration.json").read_bytes())
    ok=calculate(source,reg)
    assert ok["45_verified"] and ok["per_pid_words"]==288
    tests={}
    for label,alter in [("unrecorded one-count change",lambda r:r["per_pair_raw"][2]["P"]["D"]["scoped"].update(uv_metadata=r["per_pair_raw"][2]["P"]["D"]["scoped"]["uv_metadata"]+1)),
                        ("swapping B and D for one arm",lambda r:r["per_pair_raw"][4]["T"].update(D=r["per_pair_raw"][4]["T"]["B"])),
                        ("zero-filled missing terminal counter",lambda r:r["per_pair_raw"][5]["T"]["B"]["scoped"].update(uv_client=0))]:
        copy_=copy.deepcopy(source);alter(copy_)
        try:calculate(copy_,reg)
        except AssertionError:tests[label]=True
        else:raise AssertionError(label)
    print(json.dumps({"prior_original":hashlib.sha256(orig.read_bytes()).hexdigest(),"real_22_pairs":8,"correctly_reconstructed_45":True,
                      "original_288_values_positive":True,"damaged_controls_refused":tests},sort_keys=True))
