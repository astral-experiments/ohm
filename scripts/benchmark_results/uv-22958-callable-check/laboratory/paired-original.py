"""Independently recompute all five registered paired metrics using only an authentic result ZIP."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from statistics import median
import struct
from zipfile import ZipFile

REGISTRATION = "2d2ad20912693be58458ec355dea335e2967c0a6dd3da80e2ef43ac70640f658"
HEAD = "7e22ae2f48542868c362db465dcc2daf24017f07"
ROLES = ["fa7a_stack_ctfe318_handwritten", "fa7a_stack_ctfe318_handwritten_coroutine_callables"]
SOURCES = ["26210096e48c5c62ef4a5e8fd1aa612631b2f7d7","f22825348d834ad9a8ef3934647181fb69f778ae"]
LABELS = ("uv_client", "uv_configuration")
RUN = 41407544748
JOB = 125152889823
BOOT = "13895848-ed2e-435a-b313-9e006b9ff3e2"
ARGS = ["check","-p","uv-client","--locked","--offline","-j8"]
KEYS = ("uv_client","sum_two","uv_configuration","whole","wall")

def shafile(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def score(rows):
    assert len(rows)==6 and all(len(p)==2 and all(type(v) is int and v>0 for v in p) for p in rows)
    ratios=[Fraction(b,a) for a,b in rows]
    return {"raw":[list(x) for x in rows],"ratios":[float(v) for v in ratios],
            "median":float(median(ratios)),"range_96_875":[float(min(ratios)),float(max(ratios))],
            "hold_medians":[float(median(ratios[:3])),float(median(ratios[3:]))],
            "strict_all_six":all(b*5<a*4 for a,b in rows)}

def checks():
    assert score([(101,80)]*6)["strict_all_six"]
    assert not score([(100,80)]+[(101,80)]*5)["strict_all_six"]
    for bad in ([(100,1)]*5, [(100,0)]*6):
        try: score(bad)
        except AssertionError: continue
        raise ValueError("incomplete/zero counter accepted")

def main(archive,sha256):
    checks();archive=Path(archive)
    assert len(sha256)==64 and shafile(archive)==sha256
    with ZipFile(archive) as z:
        names=[f.filename for f in z.infolist()]
        assert len(names)==len(set(names))
        def read(name):return json.loads(z.read(name))
        prefix="native-22958/"
        positive=read(prefix+"score.json")
        assert positive["complete"] and positive["registered"]==REGISTRATION and positive["independent_histories"]==12
        assert not positive["original_exact_cold_gate_redeemed"] and positive["primary_then_secondary"]
        assert [positive["sources"][r]["commit"] for r in ROLES]==SOURCES
        boot=read("boot-attestation.json"); assert (boot["boot"],boot["run"],boot["registered"],boot["coordinator"])==(BOOT,RUN,REGISTRATION,HEAD)
        assert boot["boot"] not in boot["excluded"].split(",")
        for member, field in [("calibration.json","inherited"),("per-rustc-calibration/calibration.json","threads")]:
            assert hashlib.sha256(z.read(member)).hexdigest()==boot[field]
        cal=read("calibration.json");assert cal["unmultiplexed_calibration_clocks"]==28 and cal["ready"]["boot"]==BOOT
        seen=set();arr={k:[] for k in KEYS}
        for i in range(1,7):
            arms=[];windows=[]
            for role in ROLES:
                where=prefix+str(i)+"-"+role+"/"
                hist=read(where+"seed.json")["sha256"]; assert hist not in seen;seen.add(hist)
                native=read(where+"native-before-score.json");assert native["same_seed"] and native["canonical"]
                vector=read(where+"scoped-request.json");assert vector["command"][1:]==ARGS
                forms=read(where+"kernel-B/forms.json");assert set(forms)==set(LABELS)
                assert vector["selectors"]=={k:v[0] for k,v in forms.items() if len(v)==1}
                ah=read(where+"threads/per-rustc.json"); assert set(ah["targets"])==set(LABELS)
                assert ah["scope"]=="retired userspace instructions in the selected process and its threads"
                enrolled = read(where+"kernel-B/products.json")
                assert len(enrolled["workspace"])==39 and {k:len(v) for k,v in enrolled["externs"].items()}=={"uv_client":64,"uv_configuration":30}
                assert read(where+"bare-B/products.json")==enrolled
                for kind in ("whole","threads","wall"):
                    check=read(where+kind+"/verified.json")
                    assert check["same_seed"] and check["seed"]==hist and check["boot"]==BOOT and read(where+kind+"/products.json")==enrolled
                data={}
                for k in LABELS:
                    row=ah["targets"][k]
                    n,e,r,event=struct.unpack("<4Q",bytes.fromhex(row["raw_hex"]))
                    assert n==row["instructions"]>0 and event==row["event_id"]>0
                    assert r==e==row["time_enabled_ns"]==row["time_running_ns"]>0
                    data[k]=n
                data["sum_two"]=sum(data.values())
                wc=read(where+"whole/whole-clock.json");assert wc["code"]==wc["event_errno"]==0
                assert wc["enabled"]==wc["running"]>0 and wc["instructions"]>0
                data["whole"]=wc["instructions"]
                t=read(where+"wall/ordinary.json");assert t["mode"]=="native" and t["exit"]==0 and t["boot"]==BOOT and t["cpus"]==boot["affinity"]
                assert t["argv"]==t["invoked"]==vector["command"] and t["ns"]==t["end_ns"]-t["start_ns"]>0
                data["wall"]=t["ns"];windows.append((t["start_ns"],t["end_ns"],role));arms.append(data)
            ordered=sorted(windows)
            assert ordered[0][1]<=ordered[1][0] and [j[2] for j in ordered]==(ROLES if i%2 else list(reversed(ROLES)))
            for k in KEYS: arr[k].append([a[k] for a in arms])
        values={k:score(arr[k]) for k in KEYS}
        for k,x in values.items():
            declared=positive["metrics"][k]
            assert x["raw"]==declared["control_and_treatment"] and x["ratios"]==declared["paired_treatment_over_control"]
            assert x["median"]==declared["paired_median"] and x["hold_medians"]==declared["half_medians"] and x["range_96_875"]==declared["exact_median_interval_96_875_percent"]
            assert x["strict_all_six"]==declared["all_six_below_80_percent"]
        primary=values["uv_client"]["strict_all_six"];secondary=primary and values["sum_two"]["strict_all_six"]
        assert primary==positive["primary_terminal_confirmed"] and secondary==positive["secondary_sum_of_two_confirmed"]
        return {"run":RUN,"job":JOB,"boot":BOOT,"registration":REGISTRATION,"head":HEAD,"raw_sha256":sha256,"source_roles":dict(zip(ROLES,SOURCES)),"primary_and_secondary":[primary,secondary],"metrics":values}

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("archive",nargs="?");ap.add_argument("--sha256");ap.add_argument("--control",action="store_true");arg=ap.parse_args()
    if arg.control:
        checks();print("six strict positive, exact threshold tie, incomplete and zero controls passed")
    else: print(json.dumps(main(arg.archive,arg.sha256),indent=2,sort_keys=True))
