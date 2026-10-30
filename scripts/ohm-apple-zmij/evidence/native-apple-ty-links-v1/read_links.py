"""Recover each actual target, linker, file digest, and test verdict from raw Apple receipts."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

FIX = "pull_diagnostics::closing_deleted_file_clears_diagnostics_before_watcher_notification"
CONTROL = "pull_diagnostics::on_did_open"
XCODE = "/Applications/Xcode_16.0.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/ld"
LINKER_HASH = "2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443"
LINKERS = {"ld","ld64","ld-classic","ld-prime","ld64.lld","ld.lld","rust-lld","wild","wild-ld"}


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def command(z, prefix, result, decoded=False):
    def raw(field):
        body = z.read(prefix + field + ".gz")
        return body if decoded else gzip.decompress(body)

    def record(field):
        return json.loads(z.read(prefix + field + ".json"))

    files = {key: raw(name) for key,name in (("stdout","stdout"),("stderr","stderr"),("native_events","exec.json"))}
    assert {k:hashlib.sha256(v).hexdigest() for k,v in files.items()} == result["streams"]
    events = json.loads(files["native_events"])
    typed = list(map(json.loads, files["stdout"].splitlines()))
    good = result["state"] != "bad"
    assert result["exit"] == (0 if good else 101)
    assert typed[-1] == {"reason":"build-finished","success":good}
    assert sum(e["reason"] == "build-finished" for e in typed) == 1
    cargo = [e for e in events if PurePosixPath(e["path"]).name == "cargo"]
    assert len(cargo)==1 and cargo[0]["argv"][1:]==result["argv"][2:]
    physical = []
    relinks = []
    links = []
    registry = {}
    paths = {}
    by_registry = {}
    for event in events:
        name = PurePosixPath(event["path"]).name
        argv = event["argv"]
        if name == "rustc" and "--crate-name" in argv:
            crate = argv[argv.index("--crate-name")+1]
            if crate == "___" and any(x=="--print" or x.startswith("--print=") for x in argv):
                continue
            assert not any("ohm-branch-cache" in x for x in argv)
            (relinks if any("link-only" in x for x in argv) else physical).append(crate)
            source = [x for x in argv if "/cargo-home/registry/src/" in x and x.endswith(".rs")]
            crate_types = [t for k,t in zip(argv,argv[1:]) if k == "--crate-type"]
            if len(source)==1 and any(t in ("lib","rlib") for t in crate_types):
                suffixes = [x.split("=",1)[1] for x in argv if x.startswith(("extra-filename=","-Cextra-filename="))]
                assert len(suffixes) <= 1
                suffix = suffixes[0] if suffixes else ""
                registry["lib"+crate+suffix+".rlib"] = crate
        if name in LINKERS:
            assert event["path"]==XCODE
            output, = [v for k,v in zip(argv,argv[1:]) if k == "-o"]
            links.append(argv)
            paths[output] = paths.get(output,0)+1
            by_registry[output] = {PurePosixPath(x).name for x in argv if x.endswith(".rlib")}
    native=result["native"]
    assert native["scope"]=="kernel-exec" and native["cargo"]==1
    assert sorted(physical)==native["full"] and sorted(relinks)==native["link_only"]
    assert links==[j["argv"] for j in native["linkers"]]
    assert all(j["stock"] and j["sha"]==LINKER_HASH for j in native["linkers"])
    # The kernel stream contains argv but no cwd. A configure probe can say
    # "-o conftest". Keep that operand relative and never match it to a Cargo
    # executable. The original observer resolved those spellings at its own cwd.
    absolute = {path:n for path,n in paths.items() if PurePosixPath(path).is_absolute()}
    relative = {path:n for path,n in paths.items() if not PurePosixPath(path).is_absolute()}
    reported = result["link_outputs"]
    assert all(reported.get(path)==n for path,n in absolute.items())
    unresolved = Counter()
    for path,n in reported.items():
        if path not in absolute:
            unresolved[PurePosixPath(path).name] += n
    assert unresolved==Counter(relative)
    artifacts=[r for r in typed if r["reason"]=="compiler-artifact"]
    assert len(artifacts)==result["typed"]
    assert sorted(r["target"]["name"] for r in artifacts if not r["fresh"])==result["dirty"]
    assert sum(r["target"]["name"]=="zmij" and r["target"]["kind"]==["lib"] and not r["fresh"] for r in artifacts)==physical.count("zmij")
    outputs={}
    e2es = []
    for r in artifacts:
        path=r.get("executable")
        if not path or not r["profile"]["test"]:
            continue
        target=r["target"]
        package=r["package_id"].split("/ruff/crates/")[-1]
        key=" ".join([package,target["name"],",".join(target["kind"])])
        assert key not in outputs
        expected=result["binary_roster"][path]
        assert expected["unit"]==[r["package_id"],target["name"],target["kind"]]
        assert PurePosixPath(path).is_absolute() and expected["links"]==absolute.get(path,0)
        consumed = sorted({registry[lib] for lib in by_registry.get(path,set()) if lib in registry})
        outputs[key]={"bytes":expected["bytes"],"sha256":expected["sha"],"physical_links":expected["links"],
                       "rebuilt_registry_inputs_to_linker":consumed}
        if target["src_path"].endswith("/crates/ty_server/tests/e2e/main.rs"):
            e2es.append((path,expected))
    assert len(outputs)==len(result["binary_roster"])
    if good:
        (exe,e2e),=e2es
        assert result["e2e_links"]==paths.get(exe,0) and result["e2e"]["raw"]==e2e["sha"]
        expected=result["e2e"]["inventory"]
        names=sorted([line.removesuffix(": test") for line in raw("list-stdout").decode().splitlines()])
        assert names==expected and len(names)==len(set(names))
        assert (FIX in names)==(result["state"]=="new") and CONTROL in names
        assert record("list-exit")==0
        for test in (CONTROL, FIX) if result["state"]=="new" else (CONTROL,):
            name=test.rsplit("::",1)[1]
            assert record(name+"-exit")==0
            stdout=raw(name+"-stdout")
            assert ("test "+test+" ... ok").encode() in stdout and b"1 passed; 0 failed" in stdout
        e2e_verdict={"sha256":e2e["sha"],"text":result["e2e"]["text"],"tests":len(names),"links":paths.get(exe,0)}
    else:
        assert not e2es and result["e2e"] is None and result["e2e_links"] is None
        assert b"ohm_ty_28988_missing_name" in files["stdout"]
        assert any((r.get("message",{}).get("code") or {}).get("code")=="E0425" for r in typed)
        e2e_verdict=None
    return {"scope":result["scope"],"phase":result["label"],"state":result["state"],"typed":len(artifacts),
            "full":sorted(physical),"link_only":sorted(relinks),"all_linkers":len(links),"relative_link_outputs":relative,
            "linked_test_executables":sum(bool(v["physical_links"]) for v in outputs.values()),
            "e2e":e2e_verdict,"test_executables":outputs}


def read(path, expected):
    assert file_hash(path)==expected
    with zipfile.ZipFile(path) as z:
        assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None
        commands={}
        for name in sorted(z.namelist()):
            if not name.endswith("/verified.json"):
                continue
            rec=json.loads(z.read(name))
            if rec.get("scope") in ("focus","workspace"):
                commands[name.removesuffix("/verified.json")]=command(z,name.removesuffix("verified.json"),rec)
        assert commands
        return {"zip_sha256":expected,"commands":commands}


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("zip",type=Path)
    p.add_argument("sha256")
    p.add_argument("out",type=Path)
    args=p.parse_args()
    answer=read(args.zip,args.sha256)
    with args.out.open("xb") as f:
        f.write(gzip.compress((json.dumps(answer,sort_keys=True,separators=(",",":"))+"\n").encode(),mtime=0))
    for label,row in answer["commands"].items():
        print(label,row["typed"],len(row["full"]),len(row["link_only"]),row["all_linkers"],
              row["linked_test_executables"],len(row["test_executables"]),row["e2e"]["links"] if row["e2e"] else None)
