"""Reopen kernel thread names, counter scopes, native artifacts, and all raw calibration controls."""
from collections import Counter
from fractions import Fraction
import hashlib
import gzip
import json
from pathlib import Path
import statistics
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import artifacts

def load(path):
    return json.loads(path.read_bytes())


def clock(row, measured):
    real, n, enabled, running = map(int, row)
    assert bool(real) == measured
    if measured:
        assert n > 0 and enabled == running > 0, row
    else:
        assert n == enabled == running == 0
    return n


def observed(root, measured):
    for f, flags in [("thread.attr", 97), ("group.attr", 99), ("whole.attr", 4195)]:
        raw = (root/f).read_bytes()
        assert struct.unpack_from("<IIQQQQQ", raw) == (0,len(raw),1,0,0,3,flags) and not any(raw[48:])
    events=[line.split("\t") for line in (root/"events.tsv").read_text().splitlines()]
    assert events[0][0] == "root"
    master=int(events[0][1])
    chosen, = (r for r in events if r[0]=="exec" and r[4]=="1")
    leader=int(chosen[1])
    names={int(r[1]):r[4] for r in events if r[0]=="name"}
    assert len(names) == sum(r[0]=="name" for r in events)
    assert all(int(r[2])==leader and r[3]=="0" for r in events if r[0]=="name")
    born={int(r[1]):int(r[2]) for r in events if r[0]=="born"}
    waits={int(r[1]):int(r[2]) for r in events if r[0]=="wait"}
    assert len(born)==sum(r[0]=="born" for r in events) and len(waits)==sum(r[0]=="wait" for r in events)
    group={tid for tid,parent in born.items() if parent==leader} | {leader}
    assert group==set(names) and all(waits.get(tid)==0 for tid in group|{master})
    # A worker cannot silently spawn another process or replace its executable.
    children={int(r[2]):(int(r[1]),int(r[3])) for r in events if r[0]=="spawn"}
    assert len(children)==sum(r[0]=="spawn" for r in events)
    assert all(tid in group and event==3 for tid,(parent,event) in children.items() if parent in group)
    assert all(tid==leader or (tid in children and children[tid][0] in group) for tid in group)
    after_selection = events[events.index(chosen) + 1:]
    assert not any(r[0] == "exec" and int(r[1]) in group for r in after_selection)
    raw=[row.split("\t") for row in (root/"samples.tsv").read_text().splitlines()]
    tasks={int(tid):clock(values,measured) for kind,tid,*values in raw if kind=="task"}
    assert len(raw)==len(tasks)+2 and set(tasks)==group
    rec={kind:(int(tid),clock(values,measured)) for kind,tid,*values in raw if kind!="task"}
    assert rec["command"][0]==master and rec["compiler"][0]==leader
    aggregate, whole=rec["compiler"][1],rec["command"][1]
    if measured:
        assert aggregate<=whole+50_000 and abs(sum(tasks.values())-aggregate) <= max(500_000,aggregate//200)
    return {"leader":leader,"physical":[int(x) for x in chosen[2:4]],"names":names,
            "tasks":tasks,"compiler":aggregate,"whole":whole}


def worker_calibration(root):
    output={}
    for i,n in enumerate([0,4_000_000,0,12_000_000]):
        r=observed(root/str(i),True)
        rows={r["names"][tid]:count for tid,count in r["tasks"].items()}
        assert len(rows)==5 and sum(rows.values()) > 0
        output[i]=rows
    expected={"opt abcdefghijk":1,"opt 123456789ab":2,"cpy zyxwvutsrqp":3,"outside":5}
    for key,factor in expected.items():
        baseline=statistics.median(output[i][key] for i in [0,2])
        for position,n in [(1,4_000_000),(3,12_000_000)]:
            slope=(output[position][key]-baseline)/(2*n*factor)
            assert .98 < slope < 1.02,(key,position,slope)
    return {"cells":4,"distinct_workers":4,"two_doses":True}


def bound(total, removable):
    assert 0 <= removable < total
    return {"possibly_removable":removable,"whole":total,"speedup_ceiling":float(Fraction(total,total-removable))}


def report(root):
    enroll=load(root/"enrollment.json")
    assert enroll["order"] == (["tree","plain"] if enroll["position"]=="01" else ["plain","tree"])
    assert enroll["attempt"]=="1" and len(enroll["head"])==40
    cal=worker_calibration(root/"worker-calibration")
    baseline={}
    tree=observed(root/"tree/edit-counter",True)
    selected=(root/"tree/edit-counter/selected.argv").read_bytes().split(b"\0")
    assert selected[-1]==b"" and selected.count(b"--crate-name")==1 and selected[selected.index(b"--crate-name")+1]==b"annotate_snippets"
    assert b"--out-dir" in selected and not any(b"self-profile" in a or b"print-mono-items" in a for a in selected)
    for mode in enroll["order"]:
        d=root/mode
        states={phase:load(d/(phase+"-artifacts.json")) for phase in ["old","edit","repeat","empty"]}
        def member(h):
            body=(root/"native-objects"/h).read_bytes()
            assert hashlib.sha256(body).hexdigest()==h
            return body
        kinds=artifacts.compare(states,member)
        ids=load(d/"identities.json")
        assert Path(ids["selectors"]["rustc"][0]).name == "rustc"
        for p in ["old","edit","repeat","empty"]:
            msgs=[json.loads(x) for x in gzip.decompress((d/p/"stdout.gz").read_bytes()).splitlines()]
            typed = {m["target"]["name"]: m["fresh"] for m in msgs if m["reason"]=="compiler-artifact"}
            assert len(typed) == 4 and set(typed) == {"memchr", "unicode_width", "anstyle", "annotate_snippets"}
            assert all(fresh == (p == "repeat" or (p == "edit" and name != "annotate_snippets")) for name, fresh in typed.items())
            assert msgs[-1] == {"reason":"build-finished","success":True}
        argv=load(d/"edit/invocation.json")["argv"]
        assert argv[-len(enroll["cli"]):]==enroll["cli"]
        assert load(d/"old/invocation.json")["argv"]==enroll["cli"]
        assert load(d/"empty/invocation.json")["argv"]==enroll["cli"]
        repeat_cli=load(d/"repeat/invocation.json")["argv"]
        assert repeat_cli[-len(enroll["cli"]):]==enroll["cli"]
        oracle={p:load(d/(p+"-behavior.json")) for p in ["old","edited"]}
        assert oracle["old"]["program"]!=oracle["edited"]["program"]
        assert oracle["old"]["source"]=="old" and oracle["edited"]["source"]=="corrected"
        repeat=load(d/"repeat-perf.json"); baseline[mode]={"repeat":clock([1,repeat["instructions"],repeat["enabled"],repeat["running"]],True)}
        assert repeat["code"]==repeat["event_errno"]==0
        if mode=="plain":
            row=load(d/"edit-perf.json")
            assert row["code"]==row["event_errno"]==0
            baseline[mode]["whole"]=clock([1,row["instructions"],row["enabled"],row["running"]],True)
            continue
        assert load(d/"stable-rustc.json")[:2]==tree["physical"]
        lookup={("cpy " if kind=="copy" else "opt ")+name[:11]:(kind,name) for name,kind in kinds.items()}
        assert len(lookup)==42
        threads=[(tid,name) for tid,name in tree["names"].items() if name.startswith(("opt ","cpy "))]
        assert Counter(name for tid,name in threads)==Counter(lookup.keys())
        totals=Counter()
        per_unit={}
        for tid,name in threads:
            kind,unit=lookup[name]
            totals[kind]+=tree["tasks"][tid]
            per_unit[unit]=(kind,tree["tasks"][tid])
        baseline[mode].update({"whole":tree["whole"],"compiler":tree["compiler"],"per_unit":per_unit,
                              "worker_sums":dict(totals),"non_worker_compiler":tree["compiler"]-sum(totals.values())})
    signed=baseline["tree"]["whole"]; plain=baseline["plain"]["whole"]
    assert abs(signed-plain)/plain < .02,(signed,plain)
    maximum=totals["debug"]+totals["native"]
    return {"position":enroll["position"],"boot":load(root/"host.json")["raw_system"]["/proc/sys/kernel/random/boot_id"],
            "calibration":cal,"ordinary":baseline,"all_six":[bound(n,maximum) for n in (plain,signed)],
            "two_debug_only":[bound(n,totals["debug"]) for n in (plain,signed)]}


if __name__=="__main__":
    print(json.dumps(report(Path(sys.argv[1])),indent=2,sort_keys=True))
