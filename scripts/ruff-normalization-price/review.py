"""Independently reopen the complete kernel, Cargo, native, source and PMU originals."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import statistics
import subprocess as sp
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from records import calibrate_lifetime, digest, dump, file_hash, from_counter, load, overflow, physical, roster

PLAN = load(HERE/"registration.json")
LOCKED = load(HERE/"locked.json")
REPO = "repos/astral-experiments/ohm/"
GH = "/home/dev-user/.local/bin/gh-auto"

def download(dest, run):
    dest.mkdir(parents=True,exist_ok=True)
    def api(path):
        return json.loads(sp.check_output([GH,"api",REPO+path],cwd=HERE))
    info = api(f"actions/runs/{run}")
    jobs = api(f"actions/runs/{run}/jobs?per_page=100")["jobs"]
    artifacts = api(f"actions/runs/{run}/artifacts?per_page=100")["artifacts"]
    assert info["status"]=="completed" and info["run_attempt"]==1 and info["id"]==int(run)
    dump(dest/"official.json", {"run":info,"jobs":jobs,"artifacts":artifacts})
    for asset in artifacts:
        aid=asset["id"]
        out=dest/(str(aid)+".zip")
        if not out.exists():
            with out.open("xb") as f:
                sp.run([GH,"api",REPO+f"actions/artifacts/{aid}/zip"],cwd=HERE,stdout=f,check=True)
        assert out.stat().st_size==asset["size_in_bytes"] and "sha256:"+file_hash(out)==asset["digest"]

def read_block(z,cohort,slot,meta,run,head,originals):
    def obj(name):
        return json.loads(z.read(name))
    names = z.namelist()
    assert len(names)==len(set(names)) and all(not Path(p).is_absolute() and ".." not in Path(p).parts for p in names)
    bind=obj("binding.json")
    assert obj("complete.json")==bind and bind["order"]==PLAN["schedule"][cohort][slot]
    assert (bind["cohort"],bind["slot"],bind["head"],int(bind["run"]),bind["attempt"])==(cohort,slot,head,run,"1")
    expected_scripts={p.name:file_hash(p) for p in HERE.iterdir() if p.suffix in (".py",".rs",".json")}
    assert bind["scripts"]==expected_scripts
    assert obj("locked-archives.json")==LOCKED["archives"] and len(LOCKED["archives"])==506
    a,b=[from_counter(obj("calibrate-"+p+".json")) for p in ("single","fork")]
    assert 1.99<b/a<2.01
    ident=obj("calibration-image.json")["ident"]
    singles=[calibrate_lifetime(lambda p:z.read("lifetime-"+act+"/"+p),ident,act) for act in ("single","fork")]
    assert 0.99<singles[1]/singles[0]<1.01
    for name in names:
        if name.startswith("objects/") and name.endswith(".zst"):
            sha=Path(name).stem
            out=originals/sha
            with tempfile.TemporaryFile() as stream:
                sp.run(["zstd","-qdc"],input=z.read(name),stdout=stream,check=True)
                stream.seek(0)
                assert hashlib.file_digest(stream,"sha256").hexdigest()==sha
                if not out.exists():
                    stream.seek(0)
                    with out.open("xb") as f:
                        shutil.copyfileobj(stream,f)
            assert file_hash(out)==sha
    prices={}
    metadata={}
    for role in bind["order"]:
        spec=PLAN["roles"][role]
        s=obj("sdk-"+role+"/source.json")
        assert s=={"factory":spec["qa"],"run":str(spec["run"]),"role":"candidate","source":spec["source"],"tree":spec["tree"]}
        sdk=obj("sdk-"+role+"/sdk.json")
        assert sdk["versions"]==obj("sdk-"+role+"/reported-versions.json")
        assert spec["source"] in sdk["versions"]["rustc"] and PLAN["config"] in sdk["versions"]["cargo"]
        assert z.read("sdk-"+role+"/sdk-sha256").decode().strip()==spec["tar"]
        installed=obj("installed-"+role+".json")
        assert installed["driver"]["sha256"]==sdk["driver"]==spec["driver"]
        assert installed["rustc"]["sha256"]==sdk["rustc"]
        assert installed["cargo"]["sha256"]==PLAN["release_members"]["bin/cargo"]["sha256"]
        assert installed["Wild"]["sha256"]==PLAN["release_members"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"]["sha256"]
        costs={}
        outputs={}
        for mode,phases in PLAN["phase_plan"].items():
            mode_values={}
            prior={}
            rows={}
            for phase in phases:
                prefix=f"{role}/{mode}/{phase}/"
                raw=[json.loads(line) for line in z.read(prefix+"cargo.jsonl").splitlines()]
                saved=obj(prefix+"result.json")
                entry=obj(prefix+"entry.json")
                invalid=phase.startswith("invalid")
                rev=PLAN["old" if phase=="cold-old" else "new"]
                assert entry["status"]==(101 if invalid else 0) and entry["source"]==rev and entry["wall_ns"]>0
                assert entry["argv"]==["cargo","+ohm",mode,"-p","ruff_python_parser","--lib","--locked","--offline","--message-format=json"]
                assert raw[-1]=={"reason":"build-finished","success":not invalid}
                env=entry["environment"]
                assert set(env)=={"CARGO_BUILD_BUILD_DIR","CARGO_BUILD_JOBS","CARGO_HOME","CARGO_NET_OFFLINE","CARGO_TARGET_DIR","RUSTUP_HOME"}
                assert env["CARGO_NET_OFFLINE"]=="true" and env["CARGO_BUILD_JOBS"]=="2"
                ref=obj(prefix+"registry.json")
                reg=z.read("registry/"+ref["sha256"]+".json")
                assert digest(reg)==ref["sha256"]==saved["registry"]
                packages=json.loads(reg)
                assert len(packages)==ref["packages"] and all(v["archive"]==LOCKED["archives"][k+".crate"] for k,v in packages.items())
                version="0.1.24" if phase=="cold-old" else "0.1.25"
                target=packages["unicode-normalization-"+version]
                assert "src/lib.rs" in target["members"]
                assert digest(json.dumps(target["members"],sort_keys=True,separators=(",",":")).encode())==target["tree"]
                if invalid:
                    assert overflow(raw,PLAN["invalid"])==saved["error"]
                    continue
                typed=roster(raw,Path(bind["source"]))
                expected=PLAN["rosters"][mode]["old" if phase=="cold-old" else "edit"]
                assert typed==saved["roster"] and typed["total"]==96 and typed["all_sha256"]==expected["all_sha256"]
                if phase in ("ordinary-edit","observed-edit"):
                    assert typed==expected
                elif phase in ("cold-old","empty-new","observed-empty-new"):
                    assert typed["dirty"]==96
                elif phase=="unchanged":
                    assert typed["dirty"]==0
                else:
                    assert phase=="repaired" and typed["dirty_names"]==["ruff_python_parser"]
                val=from_counter(obj(prefix+"hardware.json"))
                assert saved["whole"]==val
                if not phase.startswith("observed-"):
                    mode_values[phase]=val
                if phase.startswith("observed-"):
                    actual=physical(lambda p:z.read(prefix+"tasks/"+p),installed,version,phase=="observed-edit")
                    assert actual==obj(prefix+"physical.json") and actual["owner"]==saved["owner"]
                    mode_values[phase+"-rustc"]=actual["owner"]
                products={}
                for crate,extensions in saved["products"].items():
                    message,=[e for e in raw if e["reason"]=="compiler-artifact" and e["target"]["name"]==crate]
                    assert set(message["filenames"])=={f["path"] for f in extensions.values()}
                    assert set(extensions)==({".rmeta",".rlib"} if mode=="build" else {".rmeta"})
                    products[crate]={}
                    for ext,f in extensions.items():
                        body=originals/f["sha256"]
                        assert body.stat().st_size==f["bytes"]
                        with body.open("rb") as stream:
                            first=stream.read(8)
                        assert first.startswith(b"rust") if ext==".rmeta" else first==b"!<arch>\n"
                        products[crate][ext]=f["sha256"]
                assert set(products)=={"ruff_python_parser","unicode_normalization"}
                record={"products":products}
                if mode=="build":
                    elf=saved["native"]["elf"]; exe=originals/elf["sha256"]
                    output=z.read(prefix+"normalizations")
                    assert digest(output)==saved["native"]["output"]==PLAN["oracle"]["old" if phase=="cold-old" else "new"]
                    assert output.decode().splitlines()[-6:]==PLAN["oracle"]["parser_checks"]
                    argv=obj(prefix+"native-argv.json")
                    for crate,m in saved["products"].items():
                        for f in m.values():
                            idx=argv.index(crate+"="+f["path"])
                            assert argv[idx-1]=="--extern"
                    assert exe.stat().st_size==elf["bytes"]
                    marker=originals/(elf["sha256"]+".actual-stdout")
                    if not marker.exists():
                        os.chmod(exe,0o700)
                        with marker.open("xb") as out:
                            sp.run([exe],cwd=originals,stdout=out,check=True)
                    assert marker.read_bytes()==output
                    record["elf"]=elf["sha256"]
                    prior["old" if phase=="cold-old" else "new"]=set(output.decode().splitlines())
                rows[phase]=record
            if mode=="build":
                assert prior["new"]-prior["old"]=={PLAN["oracle"]["sole_added"]} and not prior["old"]-prior["new"]
                assert rows["cold-old"]["elf"]!=rows["ordinary-edit"]["elf"]
            for phase,row in rows.items():
                if phase=="cold-old":
                    continue
                assert row["products"]["unicode_normalization"]==rows["ordinary-edit"]["products"]["unicode_normalization"]
                if phase in ("unchanged","observed-edit"):
                    assert row["products"]["ruff_python_parser"]==rows["ordinary-edit"]["products"]["ruff_python_parser"]
                if mode=="build":
                    assert row["elf"]==rows["ordinary-edit"]["elf"]
            assert obj(role+"/"+mode+"/terminal.json")["phases"]==phases
            costs[mode]=mode_values
            outputs[mode]=rows
        prices[role]=costs
        metadata[role]=outputs
    return {"boot":bind["boot"],"slot":slot,"order":bind["order"],"prices":prices,"outputs":metadata,
            "archive":meta["id"],"archive_digest":meta["digest"],"head":head,"run":run}

def score(cohort,blocks):
    assert {b["slot"] for b in blocks}==set(PLAN["schedule"][cohort])
    assert len({b["boot"] for b in blocks})==len(blocks)
    savings={}
    increases={}
    for mode in ("check","build"):
        for name in blocks[0]["prices"]["C5"][mode]:
            key=mode+"/"+name
            pairs=[(b["prices"]["C5"][mode][name],b["prices"]["C7"][mode][name]) for b in blocks]
            savings[key]=[100*(p-c)/p for p,c in pairs]
            increases[key]=[c-p for p,c in pairs]
    primary=savings["check/observed-edit-rustc"]; whole=savings["check/ordinary-edit"]
    gates={"whole_edit_always_favorable":all(w>0 for w in whole),
           "eligible_rustc":(all(p>=20 for p in primary) if cohort=="pilot" else min(primary)>0 and statistics.median(primary)>=20)}
    for key in savings:
        if key.split("/")[-1] not in ("cold-old","empty-new","unchanged","observed-empty-new-rustc"):
            continue
        pct=[-p for p in savings[key]]; delta=increases[key]
        red=(all(p>2 and d>10_000_000 for p,d in zip(pct,delta)) if cohort=="pilot"
             else statistics.median(pct)>2 and statistics.median(delta)>10_000_000)
        gates["common_"+key]=not red
    return {"cohort":cohort,"plan":file_hash(HERE/"registration.json"),"blocks":blocks,"savings_pct":savings,
            "gates":gates,"qualified":all(gates.values()),"median_rustc":statistics.median(primary),"median_whole":statistics.median(whole),
            "sign_two_sided":2/(2**len(primary)) if min(primary)>0 else None}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("cohort",choices=PLAN["schedule"]);p.add_argument("directory",type=Path)
    p.add_argument("--download",type=int);p.add_argument("--head",required=True);p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    if args.download:
        download(args.directory,args.download)
    official=load(args.directory/"official.json")
    run=official["run"]
    assert run["head_sha"]==args.head and run["head_branch"]=="charlie/qa-rc24-normalization-price-20261104"
    assert all(j["conclusion"]=="success" for j in official["jobs"])
    blocks=[]
    with tempfile.TemporaryDirectory() as scratch:
        for slot in PLAN["schedule"][args.cohort]:
            meta,=[a for a in official["artifacts"] if a["name"]==f"norm21229-{slot}-{run['id']}"]
            path=args.directory/(str(meta["id"])+".zip")
            assert meta["workflow_run"]["id"]==run["id"] and path.stat().st_size==meta["size_in_bytes"] and "sha256:"+file_hash(path)==meta["digest"]
            with zipfile.ZipFile(path) as z:
                blocks.append(read_block(z,args.cohort,slot,meta,run["id"],args.head,Path(scratch)))
    if args.cohort=="confirmation":
        pilot=load(HERE/"evidence/pilot/qualified.json")
        assert pilot["cohort"]=="pilot" and pilot["qualified"] and pilot["plan"]==file_hash(HERE/"registration.json")
        assert not ({b["boot"] for b in pilot["blocks"]} & {b["boot"] for b in blocks})
    verdict=score(args.cohort,blocks)
    dump(args.out,verdict)
    print(json.dumps({k:v for k,v in verdict.items() if k not in ("blocks","savings_pct")},indent=2))

if __name__=="__main__":
    main()
