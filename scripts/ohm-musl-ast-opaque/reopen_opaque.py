"""Independently check the immutable native qualification ZIP, including rebuilt ar/rmeta and restored opens."""
from pathlib import Path
import collections,errno,gzip,io,json,os,re,subprocess,sys,tarfile,tempfile,zipfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import run as gate,consumer,closure
from clocked import require,sha
from verified_state import compare,witness

LABS=("old","edit","measured-final","empty1","empty2")
MODES=(("metadata","positive"),*(("metadata",m) for m in consumer.BAD),("archive","positive"))


def run_image(raw,want):
    require(raw[:7]==bytes.fromhex("7f454c46020101") and int.from_bytes(raw[18:20],"little")==62,"native x86-64 ELF")
    fd=os.memfd_create("verified-x86-musl-native-visitor",getattr(os,"MFD_EXEC",0))
    try:
        with os.fdopen(os.dup(fd),"wb") as f:f.write(raw)
        os.fchmod(fd,0o500);env={"PATH":"/usr/bin:/bin","LC_ALL":"C"}
        try:o=subprocess.run([f"/proc/self/fd/{fd}"],pass_fds=(fd,),env=env,capture_output=True,timeout=12)
        except PermissionError:
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/"verified-musl-visitor";p.write_bytes(raw);p.chmod(0o500)
                require(sha(p.read_bytes())==sha(raw),"temporary native program integrity")
                o=subprocess.run([p],env=env,capture_output=True,timeout=12)
        require(o.returncode==0 and o.stdout.decode()==want and not o.stderr,"physical retained program")
    finally:os.close(fd)


def original_hashes(failed,screen,summary):
    from crate_deps import definitions
    with zipfile.ZipFile(failed) as bad,zipfile.ZipFile(screen) as old:
        prefix="P/consumers/literal-old/metadata-positive."
        diagnostic=gzip.decompress(bad.read(prefix+"stderr.gz"));opens=gzip.decompress(bad.read(prefix+"opens.gz"));out=gzip.decompress(bad.read(prefix+"stdout.gz"))
        ds=[json.loads(l) for l in diagnostic.splitlines() if l.startswith(b"{")]
        bads=[e for e in ds if (e.get("code") or {}).get("code")=="E0463" and e.get("message")=="can't find crate for `ruff_python_ast`"]
        require(not out and len(bads)==1 and any(b"libchar_str-" in l and b"openat" in l and b" = -1 " not in l for l in opens.splitlines()),"original missing input was not exercised")
        result={"stderr":sha(diagnostic),"opens":sha(opens),"status":"rejected E0463","char_str_lookups":sum(b"libchar_str-" in l and b"openat" in l and b" = -1 " not in l for l in opens.splitlines())}
        for a,b,s in (("old","old","old"),("measured-final","measured-final","warm"),("empty","empty1","empty")):
            def dep(z,prefix,phase):
                m=json.loads(z.read(prefix+phase+"/ar-replay.json"));h=m["separate_rmeta"]
                data=gzip.decompress(z.read(prefix+"ar-content/"+h+".gz"));require(sha(data)==h,"literal earlier bytes")
                return definitions(data)["items"]
            x=dep(old,"musl-measurements/P/proof/",a);y=dep(bad,"P/proof/",b)
            require(len(x)==len(y)==45 and [(j[0],j[1],t[1]) for j,t in zip(x,y) if j!=t]==[tuple(v) for v in summary["mismatching_hashes"]],"previous actual five hashes")
    return result


def verify(source,expected_head=None):
    with zipfile.ZipFile(source) as z:
        require(z.testzip() is None and len(z.namelist())==len(set(z.namelist())),"native source ZIP")
        read=lambda p:json.loads(z.read(p))
        raw=lambda p:gzip.decompress(z.read(p))
        source=gate.source_proof(raw("nodes.rs.gz"));require(source==read("finite-source.json"),"changed actual nodes.rs or finite decoder")
        prior=read("reopened-second-empty.json");fixed=json.loads((HERE/"historical-second-empty.json").read_bytes())
        require(prior["previous_head"]==fixed["head"] and not prior["original_qualified_roles"] and prior["old_compiler_completed_native_visits"]==5,"incorrect historical result")
        for edge,o in fixed["strict_three_priorities"].items():
            item=prior["actual"][edge];l,r=edge.split("--");b=item["bidirectional"]
            require(item["original_three_verdict"]==o["accepted"] and item["raw_changed_bytes"]==o["raw_changed_bytes"] and b["forward"]["reencoded_ar"]==fixed["visits"][r]["rlib"] and b["reverse"]["reencoded_ar"]==fixed["visits"][l]["rlib"],"prior archive commitment")
        final=read("passed.json");custody=read("custody.json")
        require(set(final)=={"P","C"} and (not expected_head or custody["workflow"]==expected_head),"unregistered result")
        output={}
        for role in "PC":
            fr=final[role];required=fr["driver"];states={};ars={};own_elf={};mismatch=read(role+"/historical-five-inputs.json")
            require(len(mismatch["old"]["items"])==len(mismatch["fresh"]["items"])==45 and len(mismatch["five"])==5 and sorted(x[0] for x in mismatch["five"])==sorted(["rustversion","castaway","thiserror","char_str","compact_str"]),"historical graph was not a real changed graph")
            traces=0;actual_units={};input_counts={};restores={};native_visits=0
            for lab in LABS:
                top=f"{role}/{role}-{lab}/";proof=f"{role}/proof/{lab}/"
                cmd=read(top+"command.json");data=raw(top+"stdout.gz");err=raw(top+"stderr.gz")
                require(cmd["exit"]==0 and cmd["stdout"]==sha(data) and cmd["stderr"]==sha(err),"real command streams")
                messages=[json.loads(line) for line in data.splitlines()]
                graph=gate.products.product(messages)[0];k=read(top+"kernel.json")
                inp=read(top+"actual-inputs.json");units=inp["units"];pidmap={str(x["pid"]):x for x in k["rustcs"]}
                require(pidmap.keys()==units.keys() and all(u["command"]==pidmap[i]["argv"] and u["name"]==pidmap[i]["crate"] and pidmap[i]["terminal"]==[0] for i,u in units.items()),"incorrect actual compiler groups")
                want=39 if lab in ("old","empty1","empty2") else (3 if role=="P" else int(lab=="edit"))
                require(len(units)==want and all(any(p.endswith(".rs") for p in u["opened_regular"]) for u in units.values()),"incomplete source reads")
                kernel=z.read(top+"execs-and-opens.tar.gz");require(sha(kernel)==inp["sha256_full_kernel"],"lost full kernel source")
                with tarfile.open(fileobj=io.BytesIO(kernel),mode="r:gz") as ar:
                    logs={t.name[5:]:ar.extractfile(t).read() for t in ar.getmembers() if t.isfile() and t.name.startswith("proc.")}
                for pid,u in units.items():
                    require(any(line.startswith(b"execve(") and bytes(required["rustc"][0],"utf-8") in line and b"--crate-name" in line and line.rstrip().endswith(b"= 0") for line in logs[pid].splitlines()),"lost actual frontend exec")
                    crew=u["thread_and_child_pids"];require(int(pid) in crew,"missing own thread")
                    files=inp["regular_files"]
                    for candidate in u["opened_regular"]:
                        require(candidate in files and re.fullmatch("[0-9a-f]{64}",files[candidate]["sha256"]) and files[candidate]["bytes"]>=0,"opened file missing hash")
                    traces+=1
                ardata=read(proof+"ar-replay.json")
                def body(h):return raw(role+"/proof/ar-content/"+h+".gz")
                w=witness(ardata,body);a,m,_,summary=w;ars[lab]=w
                rd=read(proof+"reader.json");link=read(proof+"reader-link.json")
                states[lab]=gate.fixture_state(a,m,summary,rd,graph["roster"],{i:link[i] for i in ("path","physical","linker_sha256","sha256","available_libc_a")})
                idx=read(proof+"matching-closure.json");recv=read(role+"/restored/"+lab+"/physical-files.json")
                require(set(recv)==set(idx["files"]) and len(idx["unit_ids"])==39,"lost closure files")
                for p,t in recv.items():
                    old=idx["files"][p];require((t["sha256"],t["bytes"])==(old["sha256"],old["bytes"]) and (t["dev"],t["ino"])!=(old["dev"],old["ino"]),"non-independent replay")
                for where in (role+"/consumers/"+lab,role+"/restored/"+lab+"/consumers"):
                    for mode,label in MODES:
                        root=f"{where}/{mode}-{label}";info=read(root+".json");stderr=raw(root+".stderr.gz");stdout=raw(root+".stdout.gz");events=raw(root+".opens.gz")
                        want_input=sha(m) if mode=="metadata" else sha(a);require(info["physical_driver"]==required and info["input_sha256"]==want_input and info["stderr"]==sha(stderr) and info["stdout"]==sha(stdout) and info["open_trace"]==sha(events) and len(consumer.trace_open(events.splitlines(),Path(info["path"])))==info["successful_input_opens"]>0,"unbound actual consumer")
                        parsed=[json.loads(t) for t in stderr.splitlines() if t.startswith(b"{")]
                        es=[d for d in parsed if d.get("level")=="error" and d.get("spans")]
                        if label=="positive":
                            require(info["status"]==0 and not es,"positive rejected")
                            if mode=="archive":
                                image=raw(root+".reader.gz");text=gate.r.WANT["old" if lab=="old" else "new"]+consumer.TAIL
                                require(sha(image)==info["product"] and info["reader_stdout"]==text,"archived ELF/state")
                                if lab in own_elf:require(own_elf[lab]==sha(image),"restored output differs")
                                else:own_elf[lab]=sha(image)
                                run_image(image,text)
                        else:
                            require(info["status"]==1 and len(es)==1 and es[0]["message"]=="lifetime may not live long enough","incorrect lifetime error")
                            ss=[p for p in es[0]["spans"] if p["is_primary"]];require(len(ss)==1 and ss[0]["line_start"]==3 and ss[0]["column_start"]==5 and ss[0]["label"]=="returning this value requires that `'a` must outlive `'static`" and ss[0]["text"][0]["text"].strip()=="Box::new(x."+consumer.BAD[label][2]+"())","wrong escaped lifetime")
                        native_visits+=1
                actual_units[lab]=len(units);input_counts[lab]=len(inp["regular_files"]);restores[lab]=len(recv)
            for name,left,right in (("edit-to-repeat","edit","measured-final"),("warm-to-empty1","measured-final","empty1"),("warm-to-empty2","measured-final","empty2"),("clean-to-clean","empty1","empty2")):
                proof=compare("measured-final","empty",states[left],states[right],ars[left],ars[right])
                require(proof==read(role+"/same-installation-comparisons.json")[name],"full bidirectional archive not reproducible")
            require(fr["old_augmented_elf"]==own_elf["old"] and fr["corrected_augmented_elf"]==own_elf["empty1"]==own_elf["empty2"]==own_elf["edit"]==own_elf["measured-final"]!=own_elf["old"],"old/edited semantics")
            for prefix in (role+"/historical-wrong-namespace/",role+"/restored/empty1/one-foreign-then-repair/"):
                fail=read(prefix+"receipt.json");diags=[json.loads(x) for x in raw(prefix+"stderr.gz").splitlines() if x.startswith(b"{")];events=raw(prefix+"kernel.gz")
                require(fail["code"]=="E0463" and fail["trace"]==sha(events) and len([e for e in diags if (e.get("code") or {}).get("code")=="E0463"])==1 and fail["rc"]==1,"missing true E0463")
            one=read(role+"/restored/empty1/one-foreign-then-repair/one-substitution.json");require(one["restored"] and one["logical_dependency_count"]==1 and one["actually_opened_foreign"] and all(a[0]!=a[1] for a in one["changed_native_files"].values()),"wrong isolated dependency")
            original=read(role+"/literally-reopened-historical-elfs.json");require(original["old"]["stdout"]==gate.r.WANT["old"] and original["empty"]==original["measured-final"] and original["empty"]["stdout"]==gate.r.WANT["new"],"historical actual ELF result")
            output[role]={"full_compilers":actual_units,"opened_file_identities":input_counts,"independently_restored_files":restores,"typed_or_linked_native_visits":native_visits,"actual_process_groups":traces,"valid_old":own_elf["old"],"valid_corrected":own_elf["empty1"],"historic_mismatched_five":mismatch["five"],"negative_then_repair":True}
        require(output["P"]["valid_old"]==output["C"]["valid_old"] and output["P"]["valid_corrected"]==output["C"]["valid_corrected"],"different real outcomes")
        return {"accepted":True,"run_head":custody["workflow"],"finite_source":source,"roles":output}

if __name__=="__main__":
    if len(sys.argv)==4 and sys.argv[1]=="previous":
        summary=json.loads((HERE/"historical-mixed.json").read_bytes());original_hashes(sys.argv[2],sys.argv[3],summary)
        print(json.dumps({"previous_five_and_40_unchanged":summary["mismatching_hashes"]}))
    else:print(json.dumps(verify(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None),sort_keys=True,indent=2))
