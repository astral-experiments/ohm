"""Reconstitute original ELF anchors and all physical Wild PIDs on each source state."""
from __future__ import annotations
import gzip
import io
import json
import sys
import zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from linux_common import *
from packages import CARGO,RELEASES,need,save

class Corpus:
    def __init__(self,location):
        self.p=location if isinstance(location,Path) and location.is_dir() else None
        self.z=None if self.p else zipfile.ZipFile(location)
        names=[str(q.relative_to(self.p)) for q in self.p.rglob("*") if q.is_file()] if self.p else [q.filename for q in self.z.infolist() if not q.is_dir()]
        need(len(names)==len(set(names)) and all(not n.startswith("/") and ".." not in Path(n).parts for n in names),"foreign receipt path")
        self.names=set(names)
    def get(self,s):
        need(s in self.names,"missing original "+s)
        return self.z.read(s) if self.z else (self.p/s).read_bytes()
    def json(self,s):return json.loads(self.get(s))
    def raw(self,s):return gzip.decompress(self.get(s))

def image(c,base,h):
    q=c.json(base+"/images/"+h+".json");need(q["sha256"]==h and q["chunks"],"bad ELF chunks")
    b=bytearray()
    for i,(k,n) in enumerate(q["chunks"]):
        part=c.raw(base+"/blocks/"+k+".gz")
        need(digest(part)==k and len(part)==n and (n==CHUNK or i==len(q["chunks"])-1 and 0<n<=CHUNK),"different original ELF block")
        b.extend(part)
    need(len(b)==q["size"] and digest(b)==h,"reassembled original ELF differs")
    return elf_bytes(b)

def behavior(c,where,exe,expected,state):
    q=c.json(where+"/behavior.json")
    control=c.json(where+"/e2e-snapshot.json");raw_snap=c.raw("shared/e2e-snapshot.snap.gz");miss=c.raw(where+"/e2e-missing.stdout.gz")
    cwd=expected[E2E]["manifest_path"].split("/crates/",1)[0]
    need(control["source"]==SNAPSHOT and control["sha256"]==digest(raw_snap)==SNAPSHOT_SHA and control["native_test"]==RUN_CASE and
         control["positive_runtime_env_changes"]=={"INSTA_WORKSPACE_ROOT":cwd,"INSTA_UPDATE":"no"} and
         control["argv"]==["--exact",RUN_CASE,"--test-threads=1"] and control["exe"]==expected[E2E]["executable"] and
         control["program_sha256"]==exe[E2E]["sha256"] and control["missing_root_exit"]==101 and b"0 passed; 1 failed" in miss and
         control["missing_root_body_sha256"]==SNAPSHOT_BODY_SHA and missing_snapshot_body(miss)==raw_snap.split(b"\n---\n",1)[1],"wrong actual snapshot oracle")
    need(len(q["libraries"])==2 and q["parser_case"]=="parser::tests::test_modes" and q["e2e_case"]==RUN_CASE,"different original physical readers")
    for i,record in enumerate(q["libraries"]):
        p=c.json(where+f"/ordinary-{i}.json");body=c.raw(where+f"/ordinary-{i}.stdout.gz")
        errors=[j["code"]["code"] for l in c.raw(where+f"/ordinary-{i}.invalid.stderr.gz").splitlines()
                if l.startswith(b"{") and (j:=json.loads(l)).get("code")]
        need(errors==record["invalid_code"]==["E0308"] and record["invalid_status"]==1 and
             p["exit"]==0 and p["sha256"]==record["ordinary_sha256"] and digest(body)==record["stdout"] and
             body.decode()==ORACLE["oracles"][state],"wrong actual trivia verdict or negative")
    for label,case,unit in (("parser",q["parser_case"],PARSER),("e2e",q["e2e_case"],E2E)):
        listing=c.raw(where+"/"+label+"-list.stdout.gz");verdict=c.raw(where+"/"+label+"-case.stdout.gz")
        for mode in ("list","case"):
            pr=c.json(where+"/"+label+"-"+mode+".json")
            need(pr["exit"]==0 and pr["sha256"]==exe[unit]["sha256"] and pr["exe"]==expected[unit]["executable"],"wrong native test executable")
        need(digest(listing)==q[label+"_list"] and (case+": test").encode() in listing.splitlines() and
             ("test "+case+" ... ok").encode() in verdict and b"1 passed; 0 failed" in verdict,"stale selected native test")
    return {"e2e_sha256":q["e2e_sha256"],"e2e_list_sha256":q["e2e_list"],"parser_list_sha256":q["parser_list"],
            "two_trivia_consumers":ORACLE["oracles"][state]}

def verify(c,role):
    need(c.raw("shared/fifty.json.gz")==(FIX/"fifty.json").read_bytes() and c.raw("shared/source-oracles.json.gz")==(FIX/"source-oracles.json").read_bytes() and
         c.raw("shared/historical.patch.gz")==(FIX/"historical.patch").read_bytes() and
         digest(c.raw("shared/historical.patch.gz"))==ORACLE["patch_sha256"],"different historical source or 50 destinations")
    source=c.json("shared/source.json")
    need((source["head"],source["tree"],source["historical_commit"],source["lock"],len(source["registry"]))
         ==(RUFF,TREE,HISTORY,LOCK,498) and source["original_archive"]==ENROLL["source_archive_sha256"],"foreign historical source")
    cert=c.json(role+"/custody.json");tools=c.json(role+"/tools.json");installed=c.json(role+"/installed.json")
    need(cert["source"]["release_id"]==RELEASES[role][0] and cert["archive_sha256"]==RELEASES[role][2]["x86_64-unknown-linux-gnu"][2] and
         cert["provenance"]["sources"]["rust"]["revision"]==REAL_RUST[role] and cert["provenance"]["sources"]["cargo"]["revision"]==CARGO,"not the published SDK")
    for k,r in (("cargo","bin/cargo"),("rustc","bin/rustc"),("wild","lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")):
        need(tools["tools"][k]["sha256"]==installed[r],"different actual "+k)
    dyn=tools["physical_driver"]
    need(dyn["sha256"] in installed.values() and REAL_RUST[role] in tools["versions"]["rustc"] and
         CARGO in tools["versions"]["cargo"] and b"calling init:" in c.raw(role+"/driver-loader.log.gz") and
         Path(dyn["physical"]).name.encode() in c.raw(role+"/driver-loader.log.gz"),"wrong actually loaded driver")
    snapshot={};visits={};terminal=c.json(role+"/terminal.json")
    figs=c.json(role+"/own-clean-full-cmp.json")
    for phase,state in (*STEPS,("clean-original","original"),("clean-reversed","reversed")):
        d=f"{role}/native/{phase}";q=c.json(d+"/observed.json")
        a,arts=outputs(c.raw(d+"/cargo.stdout.gz"))
        need(c.json(d+"/exit.json")==0 and c.raw(d+"/cargo.stderr.gz") is not None and q["argv"]==CMD and q["phase"]==phase and q["state"]==state and
             q["source"]=={p:h[state] for p,h in ORACLE["source"].items()} and
             not ({"CI","TF_BUILD","CARGO_INCREMENTAL","RUSTFLAGS","RUSTC_WRAPPER","GH_TOKEN","GITHUB_TOKEN"} & set(q["env"])),
             "source, ordinary Cargo command or exit changed")
        lines=json.loads(c.raw(d+"/kernel.json.gz"))
        by=native(lines,tools["tools"],c.json(d+"/exec-aliases.json"))
        need(by==q["actual"],"literal strace census differs")
        byexe=q["outputs"]; need(sorted(byexe)==sorted(arts),"different native inventory")
        for k,r in byexe.items():
            need(r["sha256"]==r["gnu_sha256"] and re.fullmatch(r"[0-9a-f]{64}",r["sha256"]) and r["path"]==arts[k]["executable"] and
                 r["size"]>0 and r["load_segments"] and ".text" in r["file_backed_allocated"] and
                 (k not in SUBJECTS or r["vault"]["physical_cmp"]==0),"wrong physical ELF")
        need(len(q["bound_wild"])==len(by["wild"]),"dropped a real Wild")
        binds=[]
        for raw,bound in zip(by["wild"],q["bound_wild"]):
            need(all(bound[k]==v for k,v in raw.items()),"PID or output differs")
            matched=[k for k,a in arts.items() if raw["output"]==a["executable"] or raw["output"] in a["filenames"]]
            if not matched and bound["dev_ino"]:matched=[k for k,v in byexe.items() if v["dev_ino"]==bound["dev_ino"]]
            need(len(matched)<2 and bound["unit"]==(matched[0] if matched else None),"different or ambiguous physical destination")
            if matched:need(byexe[matched[0]]["dev_ino"]==bound["dev_ino"],"Wild did not produce the returned inode")
            binds.append(bound)
        reader=behavior(c,d,byexe,arts,state)
        linked=[q["unit"] for q in binds if q["unit"] in SUBJECTS]
        need(len(set(linked))==len(linked),"multiple real Wild calls for a single original destination")
        if phase in ("cold","clean-original","clean-reversed"):
            need(set(linked)==set(SUBJECTS),"an empty build did not natively link all 50 historical destinations")
        visits[phase]={"all_native_counts":by["counts"],"all_physical_wild_pids":binds,"all_physical_rustcs":by["compilers"],
                       "historical_50_linked":sorted(linked),"typed_executables":len(arts),"typed_tests":sum(a["profile"]["test"] for a in arts.values()),
                       "native_readers":reader,"all_50_full_elf_sha256":{k:byexe[k]["sha256"] for k in SUBJECTS}}
        snapshot[phase]=byexe
    archive=set();failed=[];all_anchor_hashes={}
    for phase,state in STEPS:
        actual=snapshot[phase];base=snapshot["clean-"+state]
        need(set(figs[phase])==set(SUBJECTS),"incomplete original full-ELF comparison")
        for u in SUBJECTS:
            x,y=actual[u],base[u];q=figs[phase][u]
            diff=sorted(k for k in x["file_backed_allocated"].keys()|y["file_backed_allocated"].keys() if
                        x["file_backed_allocated"].get(k)!=y["file_backed_allocated"].get(k))
            need([q["actual"],q["clean"],q["size"],q["whole_file_cmp_exit"],q["different_allocated_sections"]]
                 ==[x["sha256"],y["sha256"],x["size"],int(x["sha256"]!=y["sha256"]),diff],"entire ELF trials disagree")
            if q["whole_file_cmp_exit"]:failed.append([phase,u,diff])
            if q["whole_file_cmp_exit"] or u in SENTINELS:
                archive.update((x["sha256"],y["sha256"]));all_anchor_hashes[x["sha256"]]=x;all_anchor_hashes[y["sha256"]]=y
    need(sorted(archive)==terminal["full_exceptions_and_controls"] and terminal["complete_file_comparisons"]==250,
         "missing original selected or differing body")
    for h in sorted(archive):
        physical=image(c,role+"/portable-elfs",h);expect=all_anchor_hashes[h]
        need(all(physical[k]==expect[k] for k in physical),"portable native reassembly and independent native hashers disagree")
    e2e={ph:snapshot[ph][E2E]["sha256"] for ph in snapshot}
    historical49={k for k,r in SUBJECTS.items() if r["cold_unchanged_same"]}
    for phase in ("unchanged","final-unchanged"):
        linked=set(visits[phase]["historical_50_linked"])
        visits[phase].update(historical_first_49_still_linked=sorted(historical49&linked),
                             historical_first_49_skipped=sorted(historical49-linked))
    return {"role":role,"native_sdk":REAL_RUST[role],"source":RUFF,"historical_edit":HISTORY,"original_50":50,"original_repeat_equal":49,
            "exact_250_cmp":250-len(failed),"entire_file_differences_to_own_empty":failed,
            "complete_portable_elf_bodies":len(archive),"portable_raw_elf_bytes":sum(v["size"] for v in all_anchor_hashes.values()),
            "e2e_sha256":e2e,"e2e_clean_expected_to_change":e2e["clean-original"]!=e2e["clean-reversed"],"stages":visits,"clock":False}

if __name__=="__main__":
    role=sys.argv[1];p=Path(sys.argv[2]);c=Corpus(p);q=verify(c,role)
    name=role+"/independent-linux-50.json"
    if "--record" in sys.argv:save(p/name,q)
    else:need(q==c.json(name),"hosted/independent Linux readbacks disagree")
    print("source",q["source"],"role",role,"whole ELF matches",q["exact_250_cmp"],"of 250")
    for k,v in q["stages"].items():print(k,v["all_native_counts"],len(v["historical_50_linked"]))
