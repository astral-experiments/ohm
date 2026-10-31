"""One unclocked native hosted qualification for previously retained and freshly produced Ruff metadata."""
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent; S=HERE.parent; TMP=Path(os.environ.get("RUNNER_TEMP","/unused"))
os.environ.setdefault("QA_ROOT",str(TMP/"ohm-aarch64-linux-zmij"))
sys.path.insert(0,str(HERE));sys.path.insert(1,str(S/"ohm-musl-ast-hardware"));sys.path.insert(2,str(S/"ohm-musl-ast-pair"));sys.path.insert(3,str(S/"ohm-musl-ast"))
import consumer, verified_state as v, ingress, measure, products, clocked as c, restore, lookup, ruff_loop as r
R=41173700698; HEAD="5d6abc7cf533b1a85264c18525c9f8917aeb47d3"
ORIGINAL={"P":(1,13032242373,"2a30ac5f9d11b96ad12c30849471e30e27f07110fe3460c7e05eea3d8a4ad180"),"C":(2,13031562810,"e84e00bb86c558f41970816dc1838bd7a7d60c5a8b62475f0cbcbedc4706f334")}
STORE=TMP/"opaque-origins"; OUT=TMP/"opaque-results"
SHA=c.file_sha; need=c.require; save=c.save
def check_ref():
    need(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF_NAME"]=="charlie/qa-musl-ast-opaque-lifetime-check" and os.environ["GITHUB_RUN_ATTEMPT"]=="1","unauthorized ref and run")

def api(suffix):return json.loads(ingress.request(suffix))
def seal():
    check_ref(); OUT.mkdir();STORE.mkdir()
    cfg,cert=ingress.admitted(S/"ohm-musl-ast-hardware","screen")
    located=lookup.locate(ingress.PROVIDER_RUN,ingress.PROVIDER_HEAD);need(located==cfg["source_transfer"],"changed source")
    for k in ("PROVIDER_RUN","PROVIDER_HEAD"):os.environ[k]=located[k]
    guard=restore.restore("P",ingress.SOURCE_RUN,ingress.SOURCE_HEAD,int(located["TRANSFER_ID"]),located["TRANSFER_DIGEST"],located["TRANSFER_SEAL"])
    run=api(f"runs/{R}");need((run["head_sha"],run["run_attempt"],run["status"],run["conclusion"])==(HEAD,1,"completed","failure"),"original red")
    jobs=api(f"runs/{R}/jobs?per_page=100")["jobs"];need(len(jobs)==2 and all(j["conclusion"]=="failure" for j in jobs),"two original failures")
    arts=api(f"runs/{R}/artifacts?per_page=100")["artifacts"];need(len(arts)==2,"two original ZIPs")
    original={}
    for role,(i,id_,h) in ORIGINAL.items():
        a,=[a for a in arts if a["id"]==id_];need((a["name"],a["expired"],a["digest"],a["workflow_run"]["id"],a["workflow_run"]["head_sha"])==(f"musl-ast-hardware-screen-{i}",False,"sha256:"+h,R,HEAD),role)
        raw=ingress.request(f"artifacts/{id_}/zip");p=STORE/(role+".zip");need(len(raw)==a["size_in_bytes"] and c.sha(raw)==h,role);p.write_bytes(raw)
        with zipfile.ZipFile(p) as z:need(z.testzip() is None,role)
        original[role]={k:a[k] for k in ("name","id","size_in_bytes","digest","workflow_run")}
    save(OUT/"custody.json",{"transfer":located,"failed_originals":original,"workflow":os.environ["GITHUB_SHA"],"guard":guard})

def fixture_state(archive,meta,summary,reader,graph,link):
    return {"roster":graph,"elf":reader["client"]["sha256"],"result":reader["stdout"],"elf_bytes":reader["client"]["bytes"],
            "reader_link":link,"rlib":summary["raw"],"canonical_rlib":summary["complete_canonical_sha256"],"rmeta":c.sha(meta),
            "embedded_metadata":summary["embedded_metadata"],"symbols":summary["symbols"],"object_count":len(summary["ordered_objects"]),
            "objects":c.sha(json.dumps(summary["ordered_objects"],separators=(",",":")).encode())}

def archived(role, *, materialize=True):
    path=STORE/(role+".zip");i,_,h=ORIGINAL[role];need(SHA(path)==h,"original")
    out={};expected_kernel=None
    with zipfile.ZipFile(path) as z:
        base=f"musl-measurements/{role}/";read=lambda x:json.loads(z.read(base+x))
        expected_kernel=read("proof/empty/kernel.json")
        original_witness={}
        for lab in ("old","measured-final","empty"):
            prefix="proof/"+lab+"/";manifest=read(prefix+"ar-replay.json")
            def body(h):
                raw=gzip.decompress(z.read(base+"proof/ar-content/"+h+".gz"));need(c.sha(raw)==h,h);return raw
            witness=v.witness(manifest,body);raw,meta,_,summary=witness
            place=STORE/role/lab;a=place/"libruff_python_ast.rlib"
            if materialize:
                place.mkdir(parents=True);a.write_bytes(raw);a.with_suffix(".rmeta").write_bytes(meta)
            reader=read(prefix+"reader.json");need(reader["rlib_sha256"]==summary["raw"] and reader["rmeta_sha256"]==c.sha(meta),"real original reader")
            link=read(prefix+"reader-link.json")
            original_messages = (z.read(base+"repeat/stdout.raw") if lab=="measured-final" else gzip.decompress(z.read(base+prefix+"stdout.gz")))
            graph=products.product([json.loads(l) for l in original_messages.splitlines()])[0]["roster"]
            state=fixture_state(raw,meta,summary,reader,graph,{k:link[k] for k in ("path","physical","linker_sha256","sha256","available_libc_a")})
            out[lab]=(a,state);original_witness[lab]=witness
        a,b="measured-final","empty"
        verification=v.compare(a,b,out[a][1],out[b][1],original_witness[a],original_witness[b])
        need(set(verification["strict_differences"])=={"canonical_rlib","rmeta","embedded_metadata"},"original rejection lost")
        save(OUT/(role+"-original-full-archive.json"),verification)
    return out,expected_kernel

def crate_specs(kernel):
    def allvals(args,p):return [a for a in args if a.startswith(p)]
    return sorted((a["crate"],a["link_only"],"--test" in a["argv"],tuple(allvals(a["argv"],"metadata=")),tuple(allvals(a["argv"],"extra-filename="))) for a in kernel["rustcs"])

def compare_here(proof,states,a,b,left,right):
    def witness(n):
        m=json.loads((proof/n/"ar-replay.json").read_bytes())
        return v.witness(m,lambda h:v.body(proof/"ar-content",h))
    return v.compare(left,right,states[a],states[b],witness(a),witness(b))

def work():
    check_ref();hand=json.loads((OUT/"custody.json").read_bytes());r.census.qualify.rt.SDK=restore.SDK
    hand["drivers"]=hand["guard"]["drivers"];hand["aware_cargo"]=hand["guard"]["cargos"]["aware"]
    env=r.prepare();envkeys=set(env)
    need(envkeys==measure.EXPECTED_ENV and env["CARGO_NET_OFFLINE"]=="true" and "CI" not in env,"ordinary environment")
    scratch=r.W/"opaque-consumer"; sources=consumer.setup(scratch,S/"ohm-musl-ast/client.rs");save(OUT/"sources.json",sources)
    trace=r.W/"opaque-traces";trace.mkdir()
    final={}
    for role in "PC":
        d=OUT/role;d.mkdir();proof=d/"proof";proof.mkdir();readers=d/"consumers";readers.mkdir();tools=measure.activate(restore,role,hand,d)
        frame={n:[str(tools[n]),SHA(tools[n])] for n in ("rustc","driver","cargo","wild")}
        oldset,expected_kernel=archived(role)
        measure.apply(r,env,"old");states={};samples={};training=None
        for lab,state in (("old","old"),("edit","new"),("measured-final","new"),("empty1","new"),("empty2","new")):
            if lab=="edit":measure.apply(r,env,"new")
            where,messages,k=r.census.trace_build(role+"-"+lab,trace,d,r.R,env,c.CMD)
            actual,typed=products.product(messages)
            full=[x["crate"] for x in k["rustcs"] if not x["link_only"]]
            if lab.startswith("empty") or lab=="old":
                observed=crate_specs(k);wanted=crate_specs(expected_kernel);save(where/"original-vs-local-unit-identities.json",{"actual":observed,"original":wanted})
                need(observed==wanted and len(full)==39,("wrong 39 Rust unit disambiguators",lab))
            if r.N in full:training=r.training(k["rustcs"])
            need(training is not None,lab)
            if lab=="edit":
                need(sorted(full)==sorted(["zmij","compact_str",r.N] if role=="P" else [r.N]),"real edit")
                continue
            if lab=="measured-final":need(sorted(full)==sorted(["zmij","compact_str",r.N] if role=="P" else []),"true repeat")
            capture=proof/lab;capture.mkdir();states[lab]=products.checked_reader(r,training,messages,capture,env,state)
            samples[lab]=consumer.check(training[0],training[1],scratch,readers/lab,env,r.WANT[state],frame)
            if lab=="empty1":
                for old,(a,record) in oldset.items():
                    samples["literal-"+old]=consumer.check(a,training[1],scratch,readers/("literal-"+old),env,r.WANT["old" if old=="old" else "new"],frame)
            if lab!="old":measure.park(r,role,lab)
        comparisons={}
        for name,aa,bb in (("warm-to-empty1","measured-final","empty1"),("warm-to-empty2","measured-final","empty2"),("clean-to-clean","empty1","empty2")):
            comparisons[name]=compare_here(proof,states,aa,bb,"measured-final" if aa=="measured-final" else "empty","empty")
        save(d/"same-installation-comparisons.json",comparisons)
        for key,actual in samples.items():
            same="old" if key in ("old","literal-old") else "empty1";ref=samples[same]
            need(actual["archive/positive"]["product"]==ref["archive/positive"]["product"]
                 and actual["archive/positive"]["reader_stdout"]==ref["archive/positive"]["reader_stdout"],("native targeted output",key,same))
            need(all(actual["metadata/"+m]["diagnostic"]==ref["metadata/"+m]["diagnostic"] for m in consumer.BAD),("opaque lifetime errors",key))
        need(samples["old"]["archive/positive"]["product"]!=samples["empty1"]["archive/positive"]["product"],"true visitor edit")
        final[role]={"phase_heads":{s:(k["rmeta"],k["rlib"],k["elf"]) for s,k in states.items()},"tested_samples":{k:{n:x["status"] for n,x in ss.items()} for k,ss in samples.items()},"old_augmented_elf":samples["old"]["archive/positive"]["product"],"corrected_augmented_elf":samples["empty1"]["archive/positive"]["product"],"driver":frame,"comparisons":{k:v_["strict_differences"] for k,v_ in comparisons.items()}}
        save(d/"terminal.json",final[role])
    need(all(final["P"][k]==final["C"][k] for k in ("old_augmented_elf","corrected_augmented_elf")),"cross-role targeted ELF")
    save(OUT/"passed.json",final)

if __name__=="__main__":
    if sys.argv==[sys.argv[0],"acquire"]:seal()
    elif sys.argv==[sys.argv[0],"verify"]:work()
    else:raise SystemExit("acquire | verify")
