"""Reopen original phase and filename evidence with exactly the enrolled producer readers."""
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import UUID
from packets import FACTORY, HEAD, digest, load, need, save

MODULES = {"read":"750b94aba0a68c946876a48d640c6f7a983bd8055ea62f9edf98004caa37e590",
           "orders":"38a7293cdf6efebd5eebeb33aa5ef9ec6b583f757f668373bf73528ee831b409",
           "normal_registry":"63ab7db13f84dcf2baf0cc52e8ba271f56ff172649b61a61af85100fef15746c",
           "live_family":"69e1c2cb35b0895829e412d0c717cf150f614da5d7de8660d402847a14b19813",
           "native_reference":"a7e10b0849bfee0336fca9b08ee081b03aaa6b8d274666ef1c888a58b593ef03"}
SOURCE = dict(P="a3fc6da13921586bc374586dee00883e9210aecd", C="259ad7069e47eaf08cf106f187b2b6393f7fd7c2")
# SHA-256 of the sorted logical path->physical digest map for every file, from the
# immutable factory receipt's P.json and C.json. Includes rustdoc and each driver.
FILES = dict(P="59ca0d46c655a1df75ead444cc59fef2b2d97f6ee49ef98bebd03df41fd1b7f1",
             C="bfb6ea0190ff028df019a81dfdd6437f3624dd9f27f3908307b2872c66612843")
OWNERS = ("ruff_workspace","ruff_linter")
PHASES = ("B","A","unchanged")

def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def readers(producer):
    need(subprocess.check_output(["git","-C",str(producer),"rev-parse","HEAD"], text=True).strip() == HEAD,
         "wrong reader producer checkout")
    source = producer / "scripts/ruff-upstream-mono-pilot"
    registry = producer / "scripts/ruff-indexed-check-pmu/registration.json"
    need(digest(registry) == "2689ba56cc2d2926fa63ec7946d6bf79b353e189eebe65edf862de542b3b93a3", "wrong registration")
    for key, sha in MODULES.items():
        need(digest(source / (key + ".py")) == sha, "wrong frozen reader " + key)
    sys.path.insert(0, str(source))
    modules = {key: importlib.import_module(key) for key in MODULES}
    for key, module in modules.items():
        need(Path(module.__file__).resolve() == (source / (key + ".py")).resolve(), "reader shadowed: " + key)
    return modules,load(registry)

def provenance(root, reg):
    factory = load(root / "factory.json")
    expected = {k:dict(id=v[0],bytes=v[1],digest=v[2]) for k,v in reg["factory_artifacts"].items()}
    need(factory == dict(run=FACTORY,head=reg["factory_head"],archive_sha256="4cc9311a777e2d39797ceec52c14973156b91a7aa2c3706a5859da9d25954b1d",artifacts=expected)
         and (reg["factory_run"], reg["compiler_parent"], reg["compiler_candidate"]) == (FACTORY,SOURCE["P"],SOURCE["C"]),
         "factory differs from immutable registration")
    install = load(root / "compiler-installations.json")
    need(install["schema"] == "ohm-matched-rustcs-v1" and set(install["arms"]) == {"normal","defer"},
         "wrong physical compiler pair")
    for role,label in (("P","normal"),("C","defer")):
        need(canonical(install["arms"][label]["files"]) == FILES[role], "different complete compiler map: " + role)
    cpu = load(root / "cpu.json")
    boot = UUID(cpu["boot"])
    need(str(boot) == cpu["boot"] and boot.version == 4 and bool(cpu["cpuinfo"]) and len(cpu["cpus"]) == 4
         and len(set(cpu["cpus"])) == 4 and all(type(v) is int and v >= 0 for v in cpu["cpus"]), "invalid CPU or boot")
    return {"boot": str(boot), "cpus": cpu["cpus"], "cpuinfo_sha256": canonical(cpu["cpuinfo"]),
            "factory": factory, "installed_file_map_sha256": FILES}

def graph_cost(graphs, role, session):
    need(graphs["session"] == session, "wrong source graph session")
    result = {}
    for name in ("dep_graph","paired_build_dep_graph"):
        if name not in graphs or graphs[name] is None: continue
        g = graphs[name]
        need(g["role_commit"] == SOURCE[role] and sum(g["kind_nodes"].values()) == g["nodes"]
             and sum(g["layout_bytes"].values()) == g["bytes"] and g["edges"] > 0, "incorrect physical dep graph")
        result[name] = {k:g[k] for k in ("bytes","nodes","edges")}
    result["query_cache"] = {"bytes":graphs["query_cache"]["bytes"]}
    need(result["query_cache"]["bytes"]>0 and "dep_graph" in result, "missing query cache or graph")
    return result

def donors(raw, role):
    need(set(raw) == set(OWNERS), "wrong native owner inventory")
    named, graphs = {}, {}
    for owner,entry in raw.items():
        groups = {key:[] for key in ("donor","regenerated_same_bytes","changed","created","removed")}
        records = entry["objects"]
        need(records and entry["prior"] != entry["current"], "missing physical transition")
        for name,f in sorted(records.items()):
            need(re.fullmatch(r"[a-z0-9]+\.o", name), "invalid object basename")
            a,b = f["previous"],f["current"]
            for ident,h in ((a,f["before_sha256"]),(b,f["after_sha256"])):
                need((ident is None and h is None) or
                     (isinstance(ident,list) and len(ident)==3 and all(type(v) is int and v>0 for v in ident)
                      and re.fullmatch(r"[0-9a-f]{64}", h or "")), "missing or inconsistent physical object identity")
            need(a or b, "object absent on both sides")
            kept = bool(a and b and a[:2] == b[:2])
            same = a and b and f["before_sha256"] == f["after_sha256"]
            need(f["same_inode"] is kept and (not kept or (same and a[2] == b[2])), "inconsistent physical donor")
            kind = "donor" if kept else "created" if not a else "removed" if not b else "regenerated_same_bytes" if same else "changed"
            groups[kind].append(name)
        named[owner] = groups
        graphs[owner] = {visit:graph_cost(entry[k],role,entry[session]) for visit,k,session in
                         (("B","before_graphs","prior"),("A","after_graphs","current"))}
    return named,graphs

def original_transcript(folder):
    with gzip.open(folder / "cargo.stdout.gz") as stream:
        return [json.loads(line) for line in stream]

def arm(root,role,out,modules):
    folder = root / ("0-" + role)
    raw_objects = load(folder / "objects.json")
    named,graphs = donors(raw_objects,role)
    save(out / ("objects-" + role + ".json"), raw_objects)
    save(out / ("named-" + role + ".json"), named)
    phases = {}
    state = Path(load(root / "environment.json")["CARGO_TARGET_DIR"]).parent
    for phase in (*PHASES, "repair"):
        d = folder / phase
        rows = original_transcript(d)
        placement = modules["normal_registry"].capture(rows, state, False)
        modules["normal_registry"].require(placement)
        visit = load(d / "visit.json")
        phases[phase] = {"storage":visit["storage"], "dirty":visit["dirty"],"roster":visit["roster"],"whole":visit["whole"],
                         "registry":{key:placement[key] for key in ("products","shared","sha256")}}
        need(set(visit["storage"]) == {"bytes","files"} and min(visit["storage"].values())>0, "invalid storage")
        if phase in PHASES:
            c = load(d / "clock.json")
            need(c["code"]==c["event_errno"]==0 and c["instructions"]==visit["count"]>0 and
                 c["stop"]>c["start"] and c["enabled"]==c["running"]>0,"unqualified original clock")
            phases[phase]["clock"] = c
    invalid = [r["message"] for r in original_transcript(folder / "invalid") if r.get("reason") == "compiler-message"
               and r["message"].get("level") == "error" and r["message"].get("code")]
    need(len(invalid)==1 and invalid[0]["code"]["code"]=="E0308" and
         any(x["is_primary"] and x["file_name"]=="crates/ruff_python_parser/src/lib.rs" for x in invalid[0]["spans"]),
         "wrong invalid edit or span")
    return dict(phases=phases, named=named, graphs=graphs, objects_sha256=digest(folder / "objects.json"))

def rank(root,rank_id,out,m,reg):
    out.mkdir(exist_ok=True,parents=True)
    os.environ.update(OHM_STUDY="ruff-confirm",OHM_OBSERVATION=str(rank_id))
    order, = m["orders"].assigned()
    need(order == ("PC" if rank_id%2==0 else "CP"), "registered order differs")
    identity = provenance(root,reg)
    submitted = load(root/"reopened.json")
    save(out/"submitted-reopened.json",submitted)
    # The frozen reader calls live_family.certify before consuming counters.
    m["read"].check(root, HEAD)
    reopened = load(root/"reopened.json")
    save(out/"independently-reopened.json",reopened)
    need(submitted == reopened, "producer and independent re-opened summaries differ")
    observed = {role:arm(root,role,out,m) for role in "PC"}
    for role,record in observed.items():
        need(reopened["pairs"]["0-"+role]["same"] == {k:len(g["donor"]) for k,g in record["named"].items()},
             "different recomputed per-name donor count")
    return dict(rank=rank_id,order=order,identity=identity,arms=observed,native=load(root/"native-family.json"))

def cross(root0,rooti,rev,m,work):
    outputs = [m["live_family"].reference(root,"P",rev) for root in (root0,rooti)]
    a,b = outputs
    need(a[1]==b[1] and {k:v for k,v in a[0].items() if k!="cli"} ==
         {k:v for k,v in b[0].items() if k!="cli"},"parent reference reader, verdict, or roster differs across boots")
    shas = [o[0]["cli"]["whole"] for o in outputs]
    result = dict(shas=shas, revision=rev,reader=a[0]["reader"]["whole"],roster=a[1],
                  jemalloc_build_dirs=[os.fsdecode(a[2]),os.fsdecode(b[2])])
    if shas[0]==shas[1]:
        result["proof"]={"identical":True}  # complete bodies already SHA-256-reopened on both boots
    else:
        with tempfile.TemporaryDirectory(dir=work) as temp:
            paths=[]
            for root,sha,row in zip((root0,rooti),shas,outputs):
                path=Path(temp)/sha
                with path.open("xb") as f:
                    subprocess.run(["zstd","-dcq",root/"reference-bodies"/(sha+".zst")],stdout=f,check=True)
                need(digest(path)==sha and path.stat().st_size==row[0]["cli"]["size"],"wrong original cross-boot ELF")
                paths.append(path)
            result["proof"]=m["native_reference"].compare(*paths,a[2],b[2])
    return result
