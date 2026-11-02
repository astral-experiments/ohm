"""Standalone source-and-provider qualification on a fully installed experimental rustc."""
from pathlib import Path
import collections, gzip, hashlib, json, os, runpy, shutil, struct, subprocess, sys, tempfile

HERE=Path(__file__).resolve().parent
PARENT="bd03d5709719c5f0712f84573faa01b943f68cb8"
HELP="`Clone` is not implemented because a trait bound is not satisfied"
FILES=("roster","reader","denied","overflow")
PAD=b"".join(("    // Moved bound position "+k+".\n").encode() for k in ("one","two","three","four"))
sha=lambda b:hashlib.sha256(b).hexdigest()
def write(path,data):
    path.write_text(json.dumps(data,sort_keys=True,indent=1)+"\n")

def visits(profile):
    obj=runpy.run_path(str(HERE/"profile_v9.py"))["Profile"](profile)
    out=collections.Counter();positive=0
    for kind,key,tid,lo,hi,flags in struct.iter_unpack("<QQIIII",memoryview(obj.entries)[8:]):
        start=lo|((flags&0xffff0000)<<16);end=hi|((flags&0xffff)<<32)
        if not start<end<0xfffffffffffe:continue
        tag=obj.label(kind);positive+=tag=="GenericActivity"
        if tag=="Query" and (label:=obj.label(key)).startswith("typeck_root\x1ereader::"):
            out[label.split("\x1e")[1]]+=1
    assert positive and all(v==1 for v in out.values())
    return sorted(out)

def run(compiler, source, dest, role):
    assert compiler.is_file() and role in ("control","candidate")
    dest.mkdir()
    pins=json.loads((HERE/"native-inputs.json").read_bytes())
    assert all(sha((source/(k+".rs")).read_bytes())==pins["fixture"][k+".rs"] for k in FILES)
    assert sha((HERE/"profile_v9.py").read_bytes())==pins["profile_v9"]
    sdk=compiler.parents[1]
    env={"PATH":"/usr/bin:/bin","LANG":"C","LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(sdk/"lib")}
    banner=subprocess.check_output([str(compiler),"-vV"],text=True,env=env)
    assert subprocess.check_output([str(compiler),"--print","sysroot"],text=True,env=env).strip()==str(sdk)
    assert sha(Path(__file__).read_bytes()) == pins["native"]
    assert "commit-hash: " + pins["subjects"][role] + "\n" in banner
    text=(source/"roster.rs").read_bytes();key=b"    T: Need,";assert text.count(key)==1
    sources={"A":text,"B":text.replace(key,PAD+key),"C":text.replace(key,PAD+b"    T: Different,")}
    phases=[("a","A",None,"A"),("unchanged-a","A","A",None),("edit","B","A","B"),("unchanged-b","B","B",None),("fresh-b","B",None,None),("changed","C","B",None),("fresh-changed","C",None,None)]
    matrix={}
    with tempfile.TemporaryDirectory(prefix="input-",dir=dest)as tmp:
        root=Path(tmp);w=root/"actual"
        for mode in ("ordinary","keyed","next"):
            bucket=dest/mode;bucket.mkdir();seeds={}
            for name,rev,seed,save in phases:
                if seed:shutil.copytree(seeds[seed],w)
                else:w.mkdir()
                raw=bucket/name;raw.mkdir()
                for f in FILES:(w/(f+".rs")).write_bytes(sources[rev]if f=="roster"else(source/(f+".rs")).read_bytes())
                rows={}
                real_bound="Different"if rev=="C"else"Need"
                for f in (*FILES,"dump"):
                    krate="roster"if f=="dump"else f
                    argv=[str(compiler),"--sysroot",str(sdk),"--crate-name",krate,"--edition=2024","--crate-type","rlib"if krate=="roster"else"bin","--error-format=json","-Cdebuginfo=0","-Cmetadata=clause-integrity-21041","-Cincremental=inc-"+f]
                    if mode=="next":argv.append("-Znext-solver=globally")
                    if f=="roster":argv+=["--emit=link,metadata"]
                    if f=="overflow":argv+=["--diagnostic-width=1200"]
                    if f=="dump":argv+=["--cfg","dump_clauses","--emit=metadata","-o","dump.rmeta"]
                    if krate!="roster":argv+=["--extern","roster=libroster.rlib","-L","dependency=."]
                    if mode=="keyed"and f=="reader":
                        profile=raw/"profiles";profile.mkdir();argv+=["-Zself-profile="+str(profile),"-Zself-profile-events=default,query-keys"]
                    argv.append(krate+".rs")
                    res=subprocess.run(argv,cwd=w,env=env,capture_output=True,timeout=60);assert not res.stdout
                    (raw/(f+".stdout")).write_bytes(res.stdout);(raw/(f+".stderr")).write_bytes(res.stderr)
                    ds=[json.loads(x)for x in res.stderr.splitlines()];codes=[j["code"]["code"]for j in ds if j.get("code")]
                    row={"argv":argv,"code":res.returncode,"diagnostic_codes":codes,"stderr":sha(res.stderr)}
                    if f=="roster":
                        assert res.returncode==0 and not ds;data=(w/"libroster.rmeta").read_bytes();row["rmeta"]=sha(data);(raw/"roster.rmeta.gz").write_bytes(gzip.compress(data,mtime=0))
                    elif f=="reader":
                        assert res.returncode==int(rev=="C")
                        if rev=="C":
                            assert codes==["E0277"]*(5 if mode=="next"else 3),"changed real bound must invalidate valid binaries"
                        else:
                            answer=subprocess.run([str(w/"reader")],capture_output=True,cwd=w,env=env,timeout=5)
                            assert (answer.returncode,answer.stdout,answer.stderr)==(0,b"42\n",b"")
                            row["binary"]=sha((w/"reader").read_bytes());row["output"]=answer.stdout.decode()
                            graph,=(w/"inc-reader").glob("reader-*/s-*/dep-graph.bin");data=graph.read_bytes();row["graph"]=sha(data);(raw/"reader.dep-graph.bin.gz").write_bytes(gzip.compress(data,mtime=0))
                        if mode=="keyed":
                            prof,=profile.glob("*.mm_profdata");data=prof.read_bytes();row["providers"]=visits(data);row["profile"]=sha(data);(raw/"reader.mm_profdata.gz").write_bytes(gzip.compress(data,mtime=0));shutil.rmtree(profile)
                    elif f=="denied":
                        assert res.returncode==1 and codes==["E0308","E0277","E0599"]
                        error,=[q for q in ds if(q.get("code")or{}).get("code")=="E0308"]
                        primary,=[q for q in error["spans"] if q["is_primary"]]
                        assert (primary["file_name"],primary["line_start"],primary["column_start"],primary["column_end"])==("denied.rs",9,5,18)
                        help_,=[q for q in error["children"]if q["message"]==HELP];mark,=help_["spans"];line=19 if rev=="A"else 23;pos=405 if rev=="A"else 540
                        assert (mark["file_name"],mark["line_start"],mark["line_end"],mark["column_start"],mark["column_end"],mark["byte_start"],mark["byte_end"],mark["is_primary"])==("roster.rs",line,line,8,8+len(real_bound),pos,pos+len(real_bound),True)
                        assert sources[rev][pos:pos+len(real_bound)].decode()==real_bound and mark["text"]==[{"text":"    T: "+real_bound+",","highlight_start":8,"highlight_end":8+len(real_bound)}];row["real_foreign_bound"]=[line,pos,pos+len(real_bound),real_bound]
                    elif f=="overflow":
                        assert (res.returncode,codes)==((1,["E0277"])if rev=="C"else (0,["recursion_depth_exceeding_limit"]*2)if mode=="next"else(1,["E0275"])),(rev,mode,codes)
                    else:
                        assert res.returncode==1
                        message,=[q for q in ds if q["message"]=="rustc_dump_predicates"]
                        clauses=[q["message"]for q in message["children"]]
                        terms=["std::marker::Sized",real_bound]
                        assert clauses==[f"Binder {{ value: TraitPredicate(<T as {k}>, polarity:Positive), bound_vars: [] }}"for k in terms]
                        row["clauses"]=clauses
                    rows[f]=row
                matrix[mode+"/"+name]=rows;write(raw/"commands.json",rows)
                if save:seeds[save]=root/(mode+save);w.rename(seeds[save])
                else:shutil.rmtree(w)
            for a,b in (("a","unchanged-a"),("edit","unchanged-b"),("edit","fresh-b"),("changed","fresh-changed")):
                l=matrix[mode+"/"+a];r=matrix[mode+"/"+b]
                for f in (*FILES,"dump"):
                    assert (bucket/a/(f+".stderr")).read_bytes()==(bucket/b/(f+".stderr")).read_bytes(),(mode,a,b,f)
                assert l["roster"]["rmeta"]==r["roster"]["rmeta"] and l["reader"].get("binary")==r["reader"].get("binary")
    for name,rev,_,_ in phases:
        for key,normal in matrix["ordinary/"+name].items():
            other=matrix["keyed/"+name][key];assert normal["argv"]==[s for s in other["argv"]if not s.startswith("-Zself-profile")]
            assert {k:v for k,v in normal.items()if k not in("argv","graph")}=={k:v for k,v in other.items()if k not in("argv","graph","profile","providers")}
    providers={n:matrix["keyed/"+n]["reader"]["providers"]for n,_,_,_ in phases}
    all_owners=["reader::main","reader::through_projection","reader::through_trait"]
    assert providers["a"]==providers["fresh-b"]==providers["changed"]==providers["fresh-changed"]==all_owners
    assert not providers["unchanged-a"] and not providers["unchanged-b"]
    # Its only changed direct child on the source-verified control is the exact foreign clause span.
    if role=="control":assert providers["edit"]==all_owners
    else:assert "reader::through_projection" not in providers["edit"],providers["edit"]
    report={"role":role,"source":banner,"sdk":str(sdk),"rustc_sha256":sha(compiler.read_bytes()),"controls":sha((HERE/"native-inputs.json").read_bytes()),"runs":{k:sha((dest/k/"commands.json").read_bytes())for k in matrix},"typeck":providers,"compilers":len(matrix)*5,"all_separate_native_and_profiled_inputs_outputs_equal":True,"all_warm_cold_diagnostics_rmeta_and_binaries_equal":True}
    write(dest/"accepted.json",report);print(sha((dest/"accepted.json").read_bytes()),providers["edit"])

if __name__=="__main__":
    run(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve(),sys.argv[4])
