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
import closure, consumer, crate_deps, verified_state as v, ingress, measure, products, clocked as c, restore, lookup, ruff_loop as r
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
    from reopen_opaque import original_hashes
    import io
    previous=json.loads((HERE/"historical-mixed.json").read_bytes())
    id_=previous["incompatible_archive_id"];record=api(f"artifacts/{id_}")
    need(record["digest"]=="sha256:"+previous["sha256"] and record["workflow_run"]["id"]==previous["incompatible_native_run"] and not record["expired"],"previous failed native archive")
    historical=ingress.request(f"artifacts/{id_}/zip")
    need(len(historical)==previous["bytes"] and c.sha(historical)==previous["sha256"],"prior raw ZIP")
    negative=original_hashes(io.BytesIO(historical),STORE/"P.zip",previous)
    save(OUT/"earlier-literal-E0463.json",{"fixed_inputs":previous,"exercise":negative,"artifact":record["id"]})
    newer=json.loads((HERE/"historical-second-empty.json").read_bytes())
    rejected=api(f"runs/{newer['run']}");a=api(f"artifacts/{newer['artifact']}")
    need((rejected["head_sha"],rejected["run_attempt"],rejected["conclusion"])==(newer["head"],1,"failure")
         and (a["workflow_run"]["head_sha"],a["digest"],a["size_in_bytes"],a["expired"])==(newer["head"],"sha256:"+newer["sha256"],newer["bytes"],False),"second red native original")
    historical=ingress.request(f"artifacts/{newer['artifact']}/zip")
    need(len(historical)==newer["bytes"] and c.sha(historical)==newer["sha256"],"incompatible original source")
    (STORE/"previous-complete-parent.zip").write_bytes(historical)
    save(OUT/"earlier-second-empty.json",newer)
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

def source_proof(nodes):
    decoder = HERE/"opaque_metadata.py"
    digest = SHA(decoder)
    need(digest=="7a59be4dc08224ac412add823b391738beb864eebf07b58f52e2e7ee26574dec", "changed enrolled finite decoder")
    project= v.opaque_metadata.validate_source(nodes)
    rows = [(h.hex() if isinstance(h,bytes) else h, fields[0], fields[2], fields[3], fields[4])
            for h,fields in v.opaque_metadata.CAPTURES.items()]
    need(len(rows)==len(consumer.BAD)==10 and
         {(owner,method) for _,owner,method,_,_ in rows}==
         {(owner,method) for owner,_,method in consumer.BAD.values()}, "ten public clients/source disagreement")
    return {"nodes":project,"path":"crates/ruff_python_ast/src/nodes.rs","revision":r.REV,"tree":r.TREE,
            "decoder":digest,"exact_public_receiver_captures":[list(t) for t in rows],
            "other_opaque_lifetimes_excluded":len(v.opaque_metadata.EXCLUDED)}


def earlier_second_empty(source, fixed):
    need(SHA(source)==fixed["sha256"],"earlier native artifact")
    all_witness={};states={}
    with zipfile.ZipFile(source) as z:
        need(z.testzip() is None and len(z.namelist())==len(set(z.namelist())) and "passed.json" not in z.namelist(),"earlier incomplete gate")
        def doc(name):return json.loads(z.read(name))
        for label,orig in fixed["visits"].items():
            prefix="P/proof/"+label+"/"
            w=v.witness(doc(prefix+"ar-replay.json"),lambda h:gzip.decompress(z.read("P/proof/ar-content/"+h+".gz")))
            a,m,_,summary=w
            rd=doc(prefix+"reader.json");link=doc(prefix+"reader-link.json")
            raw=gzip.decompress(z.read("P/P-"+label+"/stdout.gz"));roster=products.product([json.loads(l) for l in raw.splitlines()])[0]["roster"]
            st=fixture_state(a,m,summary,rd,roster,{k:link[k] for k in ("path","physical","linker_sha256","sha256","available_libc_a")})
            need((st["rlib"],st["rmeta"],st["elf"])==(orig["rlib"],orig["rmeta"],orig["static_original"]),"second original changed")
            for kind,rc in orig["live_native_checks"].items():
                obs=doc("P/consumers/"+label+"/"+kind.replace("/","-")+".json")
                need(obs["status"]==rc and obs["successful_input_opens"]>0,"earlier native compiler return")
                if kind=="archive/positive":need(obs["product"]==orig["augmented_old_3"],"prior physical image")
            all_witness[label]=w;states[label]=st
    result={}
    for edge,prior in fixed["strict_three_priorities"].items():
        a,b=edge.split("--");left,right=all_witness[a],all_witness[b]
        need(sum(x!=y for x,y in zip(left[1],right[1]))==prior["raw_changed_bytes"],"changed archived byte count")
        rebuilt=v.compare("measured-final","empty",states[a],states[b],left,right)
        result[edge]={"original_three_verdict":prior["accepted"],"raw_changed_bytes":prior["raw_changed_bytes"],"bidirectional":rebuilt}
    return {"previous_head":fixed["head"],"original_qualified_roles":[],"old_compiler_completed_native_visits":len(states),"actual":result}


def crate_specs(kernel):
    def allvals(args,p):return [a for a in args if a.startswith(p)]
    return sorted((a["crate"],a["link_only"],"--test" in a["argv"],tuple(allvals(a["argv"],"metadata=")),tuple(allvals(a["argv"],"extra-filename="))) for a in kernel["rustcs"])

def compare_here(proof,states,a,b,left,right):
    def witness(n):
        m=json.loads((proof/n/"ar-replay.json").read_bytes())
        return v.witness(m,lambda h:v.body(proof/"ar-content",h))
    return v.compare(left,right,states[a],states[b],witness(a),witness(b))

def deps_diff(older, newer):
    a=crate_deps.definitions(older);b=crate_deps.definitions(newer)
    need(len(a["items"])==len(b["items"])==45 and [(r[0],r[2:]) for r in a["items"]]==[(r[0],r[2:]) for r in b["items"]],"mixed graph structure changed")
    changes=[[x[0],x[1],y[1]] for x,y in zip(a["items"],b["items"]) if x[1]!=y[1]]
    need({row[0] for row in changes}=={"rustversion","thiserror","castaway","char_str","compact_str"} and len(changes)==5,("unexpected historical hashes",changes))
    return {"old":a,"fresh":b,"five":changes}


def original_binaries(role,oldset):
    outputs={}
    for label, (_,state) in oldset.items():
        digest=state["elf"];target=STORE/(role+"/original-visitor-"+digest)
        with zipfile.ZipFile(STORE/(role+".zip")) as z:
            data=subprocess.check_output(["zstd","-qdc"],input=z.read("musl-ast/receipts/images/"+digest+".zst"))
        need(c.sha(data)==digest and data[:7]==bytes.fromhex("7f454c46020101") and len(data)==state["elf_bytes"],"original complete ELF")
        if not target.exists():target.write_bytes(data);target.chmod(0o500)
        out=subprocess.check_output([target],timeout=12)
        expected=r.WANT["old" if label=="old" else "new"]
        need(out.decode()==state["result"]==expected,"historical visitor runtime")
        outputs[label]={"sha256":digest,"bytes":len(data),"stdout":out.decode()}
    save(OUT/role/"literally-reopened-historical-elfs.json",outputs)


def same(actual, prior, label):
    need(actual["archive/positive"]["product"]==prior["archive/positive"]["product"]
         and actual["archive/positive"]["reader_stdout"]==prior["archive/positive"]["reader_stdout"],("actionable native result",label))
    need(all(actual["metadata/"+m]["diagnostic"]==prior["metadata/"+m]["diagnostic"] for m in consumer.BAD),("invalid lifetime results",label))


def work():
    check_ref();hand=json.loads((OUT/"custody.json").read_bytes());r.census.qualify.rt.SDK=restore.SDK
    hand["drivers"]=hand["guard"]["drivers"];hand["aware_cargo"]=hand["guard"]["cargos"]["aware"]
    env=r.prepare()
    nodes=(r.R/"crates/ruff_python_ast/src/nodes.rs").read_bytes()
    save(OUT/"finite-source.json",source_proof(nodes))
    (OUT/"nodes.rs.gz").write_bytes(gzip.compress(nodes,mtime=0))
    prior=json.loads((HERE/"historical-second-empty.json").read_bytes())
    save(OUT/"reopened-second-empty.json",earlier_second_empty(STORE/"previous-complete-parent.zip",prior))
    need(set(env)==measure.EXPECTED_ENV and env["CARGO_NET_OFFLINE"]=="true" and "CI" not in env,"ordinary environment")
    scratch=r.W/"opaque-consumer";sources=consumer.setup(scratch,S/"ohm-musl-ast/client.rs");save(OUT/"sources.json",sources)
    trace=r.W/"opaque-traces";trace.mkdir();pool=TMP/"native-closure-content"
    all_roles={};stamps={}
    for role in "PC":
        d=OUT/role;d.mkdir();proof=d/"proof";proof.mkdir();readers=d/"consumers";readers.mkdir()
        tools=measure.activate(restore,role,hand,d)
        frame={n:[str(tools[n]),SHA(tools[n])] for n in ("rustc","driver","cargo","wild")}
        oldset,expected_kernel=archived(role);original_binaries(role,oldset)
        measure.apply(r,env,"old");states={};samples={};frozen={};training=None;cold=None
        for label,state in (("old","old"),("edit","new"),("measured-final","new"),("empty1","new"),("empty2","new")):
            if label=="edit":measure.apply(r,env,"new")
            where,messages,k,actual=closure.observe(r,role+"-"+label,trace,d,env,c.CMD,stamps)
            full=[x["crate"] for x in k["rustcs"] if not x["link_only"]]
            if label.startswith("empty") or label=="old":
                observed=crate_specs(k);wanted=crate_specs(expected_kernel);save(where/"original-vs-local-unit-identities.json",{"actual":observed,"original":wanted})
                need(observed==wanted and len(full)==39 and len(actual["units"])==39,("wrong 39 independently opened units",label))
                cold=actual
            elif label=="edit":need(sorted(full)==sorted(["zmij","compact_str",r.N] if role=="P" else [r.N]),"real visitor edit")
            else:need(sorted(full)==sorted(["zmij","compact_str",r.N] if role=="P" else []),"true unchanged repeat")
            if r.N in full:training=r.training(k["rustcs"])
            need(training is not None and cold is not None,label)
            cap=proof/label;cap.mkdir();states[label]=products.checked_reader(r,training,messages,cap,env,state)
            samples[label]=consumer.check(training[0],training[1],scratch,readers/label,env,r.WANT[state],frame)
            frozen[label]=closure.snapshot(r,cold,actual,messages,training,pool,cap,readers/label)
            if label=="empty1":
                wrong=consumer.wrong_provider(oldset["old"][0],training[1],scratch,d/"historical-wrong-namespace",env,frame)
                differences=deps_diff(oldset["old"][0].with_suffix(".rmeta").read_bytes(),training[0].with_suffix(".rmeta").read_bytes())
                save(d/"historical-five-inputs.json",differences)
            if label in ("measured-final","empty1","empty2"):measure.park(r,role,label)
        for lab,z in samples.items():same(z,samples["old" if lab=="old" else "empty1"],lab)
        need(samples["old"]["archive/positive"]["product"]!=samples["empty1"]["archive/positive"]["product"],"historical visitor edit disappeared")
        all_roles[role]={"frame":frame,"states":states,"samples":samples,"frozen":frozen,"mixed":wrong["code"],"five":differences["five"]}
        save(d/"all-five-live-downstream.json",{"driver":frame,"states":{k:{"rmeta":s["rmeta"],"rlib":s["rlib"]} for k,s in states.items()},"source_visits":{k:{n:q["status"] for n,q in z.items()} for k,z in samples.items()}})
    final={}
    for role in "PC":
        info=all_roles[role];d=OUT/role;(d/"restored").mkdir();tools=measure.activate(restore,role,hand,d/"restored")
        fr=info["frame"];need(all(SHA(tools[n])==w[1] for n,w in fr.items()),"same exact reopened compiler stack")
        independent={};foreign=all_roles["C" if role=="P" else "P"]["frozen"]["empty1"]
        for label,index in info["frozen"].items():
            dest=d/"restored"/label;dest.mkdir()
            with closure.restore(index,pool) as (a,search,physical):
                save(dest/"physical-files.json",physical)
                if label=="empty1":
                    closed=closure.swap(index,foreign,pool,consumer,a,search,scratch,dest/"one-foreign-then-repair",env,fr)
                native=consumer.check(a,search,scratch,dest/"consumers",env,r.WANT["old" if label=="old" else "new"],fr)
                same(native,info["samples"][label],label+" reopened")
                independent[label]={k:v["status"] for k,v in native.items()}
        j={"phase_heads":{s:(v["rmeta"],v["rlib"],v["elf"]) for s,v in info["states"].items()},
           "tested_samples":{k:{n:x["status"] for n,x in ss.items()} for k,ss in info["samples"].items()},
           "independently_reopened":independent,"old_augmented_elf":info["samples"]["old"]["archive/positive"]["product"],
           "corrected_augmented_elf":info["samples"]["empty1"]["archive/positive"]["product"],"driver":fr,
           "historical_mixed_diagnostic":info["mixed"],"historical_mixed_hashes":info["five"],
           "one_foreign_dependency_rejected":closed["rejected"]["code"],"one_foreign_dependency_repaired":closed["restored"]}
        save(d/"all-five-independently-restored.json",j)
        final[role]=j
    need(all(final["P"][k]==final["C"][k] for k in ("old_augmented_elf","corrected_augmented_elf")),"cross-role semantic ELF")
    # Both native positive and adverse histories survive a later refusal by the exact byte-format verifier.
    for role in "PC":
        d=OUT/role;states=all_roles[role]["states"];comparisons={}
        for label,a,b in (("edit-to-repeat","edit","measured-final"),("warm-to-empty1","measured-final","empty1"),("warm-to-empty2","measured-final","empty2"),("clean-to-clean","empty1","empty2")):
            comparisons[label]=compare_here(d/"proof",states,a,b,"measured-final","empty")
            save(d/("bidirectional-"+label+".json"),comparisons[label])
        save(d/"same-installation-comparisons.json",comparisons)
        final[role]["comparisons"]={k:j["strict_differences"] for k,j in comparisons.items()}
        save(d/"terminal.json",final[role])
    save(OUT/"passed.json",final)

if __name__=="__main__":
    if sys.argv==[sys.argv[0],"acquire"]:seal()
    elif sys.argv==[sys.argv[0],"verify"]:work()
    else:raise SystemExit("acquire | verify")
