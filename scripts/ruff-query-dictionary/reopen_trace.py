"""Recover the accepted signed trace's real decisions before joining dictionary names."""
import collections
import contextlib
import gzip
import hashlib
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"ruff-cgu-inputs/cgu-probe"))
sys.path.insert(0,str(HERE.parent/"ruff-cgu-inputs"))
import graph
import verify_trace
from read_products import recorded_products

ORIGIN = "green-reasons/A/stage/ruff_workspace/"
RUN = 41417607187
HEAD = "bd7b58765ae44b21a1c9273b3ff0be8e923adc47"
DIGEST = "39f0cc2151dbfd7825e60097c77a9cc9a53d5b4393dce69a6e41ce00287b7ec8"


def load(archive, name):
    return json.loads(archive.read(name))


def anonymous(stack, label, stream, length, digest):
    assert 0 < length < 256 << 20
    target = stack.enter_context(os.fdopen(os.memfd_create(label), "w+b"))
    total = 0
    h = hashlib.sha256()
    while data := stream.read(1 << 20):
        total += len(data)
        assert total <= length
        h.update(data)
        target.write(data)
    assert total == length and h.hexdigest() == digest
    target.flush()
    return Path("/proc/self/fd/" + str(target.fileno()))


def examine(archive, saved):
    consent = load(archive,"accepted.json")
    enrolled = load(archive,"enrollment.json")
    record = load(archive,"green-probe-reasons.json")
    before = load(archive,ORIGIN+"green-inputs-exec.json")
    after = load(archive,"green-reasons/A/green-inputs-after.json")
    assert consent["run"] == enrolled["run"] == RUN and consent["head"] == HEAD and consent["boot"] == enrolled["boot"]
    assert consent["job"] == enrolled["job"] == 125185179080
    assert before["incremental"] == after["incremental"]
    assert before["original_argv_sha256"] == after["original_argv_sha256"] == hashlib.sha256(archive.read(ORIGIN+"original.nul")).hexdigest()
    old, = before["sessions"]
    new, = [s for s in after["sessions"] if s["path"] != old["path"]]
    old_files = {r["name"]:r for r in old["files"]}
    new_files = {r["name"]:r for r in new["files"]}
    assert all(f["dep-graph.bin"]["sha256"] == f["ohm-build-dep-graph.bin"]["sha256"] for f in (old_files,new_files))
    leaves = {key:entry for key,entry in (("prior_graph",old_files["dep-graph.bin"]),("current_graph",new_files["dep-graph.bin"]),("work_products",old_files["work-products.bin"]))}
    trace = archive.read(ORIGIN+"cgu.log")
    assert hashlib.sha256(trace).hexdigest() == record["source_sha256"]["trace"] == consent["signed_workspace_decisions"]["log"]
    launch = load(archive,ORIGIN+"launch.json")
    observed = {int(p[2]):list(map(int,p[3:])) for l in trace.decode().splitlines() if (p:=l.split())[:2] == ["CGUR","FD"]}
    assert len(launch["fds"]) == consent["signed_workspace_decisions"]["original_fd_count"]
    assert max(f[0] for f in launch["fds"]) > 64 and all(observed.get(f[0]) == f[1:] for f in launch["fds"])
    size = sum(f["stat"][2] for f in leaves.values())
    available = int(next(x.split()[1] for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable:")))*1024
    assert available > (8 << 30) + size + (128 << 20)
    with contextlib.ExitStack() as stack:
        raw = {}
        for label,row in leaves.items():
            body=archive.read("green-originals/"+row["sha256"]+".gz")
            assert hashlib.sha256(body).hexdigest() == record["source_sha256"][label]
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as z:
                raw[label]=anonymous(stack,label,z,row["stat"][2],row["sha256"])
        log=anonymous(stack,"signed-decisions",io.BytesIO(trace),len(trace),record["source_sha256"]["trace"])
        result=verify_trace.evidence(raw["prior_graph"],raw["current_graph"],raw["work_products"],verify_trace.trace(log))
        donor=recorded_products(raw["work_products"].read_bytes(),old_files)
        by_id={"".join(f"{w:016x}" for w in row["words"]):row for row in donor.values()}
        for dec in result["decisions"]:
            d=by_id.get(dec["work_product_id"])
            dec["prior_saved_files"]=None if d is None else d["saved"]
            dec["prior_saved_files_present"]=None if d is None else d["all_present"]
            assert d and d["all_present"] and d["cgu"] == dec["cgu"]
        assert json.loads(json.dumps(result)) == {k:record[k] for k in result}
        donor_names={(r["kind"],r["key"]):r for r in saved["primary"]+saved["context"]}
        all_keys={(n["kind"],n["key"]) for d in result["decisions"] for j in d["observed_rejections"] for n in j["path"]}
        assert set(donor_names) == all_keys
        by_branch={}
        for branch,label in (("A","current_graph"),("B","prior_graph")):
            _, rows=graph.graph(raw[label],keys=all_keys)
            index=collections.defaultdict(list)
            for row in rows.values():
                index[row["kind"],row["key"]].append((row["index"],row["value"]))
            by_branch[branch]=index
        primary=[]
        for d in result["decisions"]:
            if d["reason"]=="green":
                continue
            n=d["observed_rejections"][-1]["path"][-1]
            ident=(n["kind"],n["key"])
            originally=donor_names[ident]
            assert originally["status"]=="unique" and len(originally["rows"])==2
            orig,=[o for o in originally["selection"] if o["cgu"]==d["cgu"] and o["reason"]==d["reason"]]
            for branch,value,i in (("A","current_value","current_index"),("B","previous_value","previous_index")):
                assert by_branch[branch][ident] == [(n[i],n[value])]
                row,=[row for row in originally["rows"] if row["branch"]==branch]
                assert orig["node"][value] == row["value"] == n[value] and row["item"]
            primary.append({"cgu":d["cgu"],"kind":n["kind"],"key":n["key"],"query":n["name"],"reason":d["reason"],"current_index":n["current_index"],"previous_index":n["previous_index"],"current_value":n["current_value"],"previous_value":n["previous_value"]})
    return {"accepted_run":RUN,"head":HEAD,"job":enrolled["job"],"boot":enrolled["boot"],"runner":enrolled["runner"],
            "runner_id":enrolled["runner_id"],"digest":DIGEST,"registered_fds":len(launch["fds"]),"largest_registered_fd":max(f[0] for f in launch["fds"]),
            "raw_digests":{k:v["sha256"] for k,v in leaves.items()},"stored_digests":record["source_sha256"],"counts":result["counts"],"decisions":len(result["decisions"]),"context_count":len(all_keys),
            "primary":sorted(primary,key=lambda v:v["cgu"])}
