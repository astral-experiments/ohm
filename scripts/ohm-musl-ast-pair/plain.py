"""Run the registered build outside tracing; validate a separately compiled ordinary reader."""
import collections
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import restore
s=restore.s
import ruff_loop as r


def capacities():
    observed=set(); payloads=collections.defaultdict(set); sizes=collections.Counter(); kind_count=collections.Counter()
    for base in ("target","shared"):
        for d,_,fs in os.walk(r.W/base):
            for name in fs:
                p=Path(d)/name
                if not p.is_file() or p.is_symlink():continue
                st=p.stat();ident=(st.st_dev,st.st_ino)
                if ident in observed:continue
                observed.add(ident)
                if p.suffix in (".o",".rlib",".rmeta",".rlink",".so"):
                    payloads[p.suffix,s.sha(p)].add(ident);kind_count[p.suffix]+=1;sizes[p.suffix]+=st.st_blocks*512
    duplicated={f"{suffix}:{digest}":len(vals) for (suffix,digest),vals in payloads.items() if len(vals)>1}
    return {"all":r.tree_bytes(),"allocated_code_payload_by_type":sizes,"code_payload_count":kind_count,
            "exact_duplicate_payloads_on_distinct_inodes":duplicated}


def main(role, e):
    path=s.LOG/"ordinary";path.mkdir()
    assert not (r.W/"target").exists() and not (r.W/"shared").exists()
    assert not r.call(["git","diff","--name-only"],e)
    source=json.loads((s.LOG/"build/empty/kernel.json").read_text())
    trained=r.training(source["rustcs"])
    cmd=["cargo","+ohm","build","--locked","--offline","-p",r.N,"--lib","--target",r.T,"-j4","--message-format=json"]
    result={}; bad=r.R/r.FILES[0]
    def visit(label,expect):
        d=path/label;d.mkdir()
        p=subprocess.run(cmd,env=e,cwd=r.R,capture_output=True,timeout=2400)
        r.census.blob(d/"stdout.jsonl.gz",p.stdout);r.census.blob(d/"stderr.gz",p.stderr)
        msgs=[json.loads(l) for l in p.stdout.splitlines()]
        assert p.returncode==(0 if expect else 101) and msgs[-1]=={"reason":"build-finished","success":bool(expect)}, (label,p.returncode,p.stderr[-1200:])
        typed=[x for x in msgs if x["reason"]=="compiler-artifact"]
        roots=[x for x in typed if x["target"]["name"]==r.N and x["profile"]["test"] is False]
        if label in ("old","empty"):assert not any(row["fresh"] for row in typed)
        rec={"cmd":cmd,"fresh":[[x["package_id"],x["target"]["name"],x["fresh"]] for x in typed],"capacity":capacities(),"exit":p.returncode}
        if expect:
            root,=roots
            arc,=(Path(n) for n in root["filenames"] if n.endswith(".rlib"))
            rec["observed"]=r.client(trained,arc,d,e,r.WANT[expect])
        else:
            assert any(m["reason"]=="compiler-message" and (m["message"].get("code") or {}).get("code")=="E0425" and r.BAD in m["message"]["rendered"] for m in msgs)
        result[label]=rec;s.save(d/"projection.json",rec)
    r.call(["git","apply","--reverse",r.PATCH],e);visit("old","old")
    r.call(["git","apply",r.PATCH],e);visit("edit","new");visit("repeat","new")
    with bad.open("a") as f:f.write("\nconst _: usize = "+r.BAD+";\n")
    visit("invalid",None);r.call(["git","restore","--worktree","--",r.FILES[0]],e);visit("repair","new")
    closed=r.W/"closed"/"ordinary-warm";closed.mkdir(parents=True)
    for k in ("target","shared"):(r.W/k).rename(closed/k)
    visit("empty","new")
    client=result["empty"]["observed"]["client"]
    assert all(result[n]["observed"]["client"]==client for n in ("edit","repeat","repair"))
    assert result["old"]["observed"]["client"]!=client
    # The independent complete ELF for the first baseline was retained in its official source archive.
    assert client==restore.q.PREVIOUS["outputs"]["build"]
    s.save(path/"terminal.json",{"role":role,"all":result,"clean":client})


def structural(role):
    e=r.prepare()
    keep={n:r.study(n,e) for n in ("build","test")}
    import native
    keep["hard-native"]=native.screen(e)
    main(role,e)
    markers={};report={}
    for mode in ("build","test"):
        record=json.loads((s.LOG/mode/"terminal.json").read_text())
        assert record["outputs"]["empty"]["client"]==restore.q.PREVIOUS["outputs"][mode]
        markers[mode]={}
        for phase in ("old","edited","unchanged","second-unchanged","repair","empty"):
            d=s.LOG/mode/phase
            emits=json.loads((d/"emitted.json").read_text())
            found={}
            for u in emits:
                if u["crate"] not in ("zmij","compact_str","ruff_python_ast") or u["target"]!=[r.T] or u["link_only"]:
                    continue
                contents=r.gzip.decompress((d/"depfiles"/(u["dep_sha"]+".gz")).read_bytes())
                assert r.census.digest(contents)==u["dep_sha"] and r.census.marker(contents)==u["marker"]
                found[u["crate"]]=[u["marker"],u["dep_sha"]]
            markers[mode][phase]=found
        s.save(s.LOG/(mode+"-markers.json"),markers[mode])
        for phase in ("old","empty"):
            rows={n:t[0] for n,t in markers[mode][phase].items()}
            assert set(rows)=={"zmij","compact_str","ruff_python_ast"}
            if role=="P":
                assert rows=={"zmij":"hard","compact_str":"hard","ruff_python_ast":"hard" if mode=="build" else "none"},rows
        report[mode]={}
        for phase in ("unchanged","second-unchanged"):
            rows=record["visits"][phase]["emitted"]
            full=[n for n,_,_,only in rows if not only]
            report[mode][phase]={"full":full,"still_full_locked":sorted(set(full)&{"zmij","compact_str"}),
                                 "still_full_root":"ruff_python_ast" in full}
            if mode=="build":
                if role=="P":assert sorted(full)==sorted(["zmij","compact_str","ruff_python_ast"]), (role,phase,rows)
                assert not record["visits"][phase]["link_tools"]
    assert all(keep.values()),keep
    s.save(s.LOG/"qualified-ordinary.json",{"role":role,"structural":keep,"repeated_compilers":report,"source":restore.q.SOURCE})


if __name__=="__main__":structural(sys.argv[1])
