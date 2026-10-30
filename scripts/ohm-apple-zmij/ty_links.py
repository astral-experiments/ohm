"""Census of actual Apple test link outputs on Ruff's deleted-document diagnostic fix."""

import collections
import json
import os
from pathlib import Path
import subprocess

from execs import ExecTrace
from local_dev import observe
from measure import capture, fresh, native_rows, retire, select
from prepare import prepare_ruff
from study import ZMIJ_LIB, check_host, compress_bytes, digest, env_for, git, need, save, sdk_id, sha, text_git
from verbs import macho_text

A = "2d253467b5153f82d26c51d49eb8d4156f1768bf"
B = "aa9a1ff88aa83b3f01360ef5b3cb04b2be187206"
TREES = {A:"89f0f1131309874e69c05e241e5d8435699a97d1", B:"b9e3804adebb8385962701bbb100eff2d6e42743"}
LOCK = "583d2c16902903b32c016859c12131cb80fd8bdc4121440f359ef743675fc1c5"
FOLDER = Path("crates/ty_server")
E2E = FOLDER / "tests/e2e/main.rs"
NEW = "pull_diagnostics::closing_deleted_file_clears_diagnostics_before_watcher_notification"
EXISTING = "pull_diagnostics::on_did_open"
ERROR = "ohm_ty_28988_missing_name"


class CensusTrace(ExecTrace):
    def command(self, argv, **kwargs):
        return super().command(argv, timeout=2100, **kwargs)


def enrolled(repo):
    need(text_git(repo,"rev-parse","HEAD")==A and text_git(repo,"rev-parse",B+"^")==A, "wrong Ruff revisions")
    need(set(git(repo,"diff","--name-only",A,B).decode().splitlines())==
         {"crates/ty_server/src/session.rs","crates/ty_server/tests/e2e/pull_diagnostics.rs"}, "unexpected patch")
    for rev,tree in TREES.items():
        need(text_git(repo,"rev-parse",rev+"^{tree}")==tree and digest(git(repo,"show",rev+":Cargo.lock"))==LOCK, "wrong tree or lock")


def checkout(repo, state):
    rev=A if state=="old" else B
    git(repo,"restore","--source",rev,"--staged","--worktree","--",".")
    need(text_git(repo,"write-tree")==TREES[rev] and not git(repo,"diff","--name-only").strip(), "incomplete real edit")
    need(sha(repo/"Cargo.lock")==LOCK and text_git(repo,"rev-parse","HEAD")==A, "Ruff identity changed")
    if state=="bad":
        with (repo/FOLDER/"src/session.rs").open("ab") as f:
            f.write(("\nconst OHM_TY_BAD: usize = "+ERROR+";\n").encode())


def actual_tests(exe, repo, env, state, out):
    environment=env|{"INSTA_UPDATE":"no"}
    def invoke(label, argv):
        p=subprocess.run([str(exe),*argv],cwd=repo/FOLDER,env=environment,capture_output=True,timeout=240)
        compress_bytes(out/(label+"-stdout.gz"),p.stdout)
        compress_bytes(out/(label+"-stderr.gz"),p.stderr)
        save(out/(label+"-exit.json"),p.returncode)
        need(p.returncode==0, f"native test {label} failed: {p.stderr[-400:]!r}")
        return p.stdout
    inventory=invoke("list",["--list","--format","terse"]).decode().splitlines()
    need(all(n.endswith(": test") for n in inventory) and len(set(inventory))==len(inventory), "unexpected e2e catalog")
    names=sorted(n.removesuffix(": test") for n in inventory)
    need(EXISTING in names and (NEW in names)==(state=="new"), "stale e2e executable catalog")
    for case in [EXISTING]+([NEW] if state=="new" else []):
        stdout=invoke(case.rsplit("::",1)[1],["--exact",case,"--test-threads=1"])
        need(("test "+case+" ... ok").encode() in stdout and b"1 passed; 0 failed" in stdout, "wrong selected test verdict")
    return {**macho_text(exe), "inventory":names}


def output_name(link):
    outs=[p for a,p in zip(link["argv"],link["argv"][1:]) if a=="-o"]
    need(len(outs)==1,"unidentified native output")
    return str(Path(outs[0]).resolve())


def collect(root, scope, work, sdk, env, trace, dest, state, label):
    repo=root/"ruff"
    argv=["cargo","+ohm","test",*(["-p","ty_server","--test","e2e"] if scope=="focus" else ["--workspace"]),
          "--no-run","--locked","--offline","-j4","--message-format=json"]
    code,stdout,stderr,events,clock=capture(argv,repo,env,dest,trace)
    ok=state!="bad"
    need(code==(0 if ok else 101),f"wrong Cargo verdict {code}: {stderr[-1000:]!r}")
    stream=list(map(json.loads,stdout.splitlines()))
    need(stream[-1]=={"reason":"build-finished","success":ok}, "incomplete Cargo JSON")
    units=[r for r in stream if r["reason"]=="compiler-artifact"]
    zmij=[r for r in units if r["target"]["name"]=="zmij" and r["target"]["kind"]==["lib"]]
    need(zmij and all(sha(z["target"]["src_path"])==ZMIJ_LIB for z in zmij),"wrong locked zmij")
    if ok and label in ("cold","edit","clean"):
        observe(events, work, sdk, {"e2e","ty_server"}, dest)
    native=native_rows(events,sdk)
    need(native["cargo"]>=1 and all(l["stock"] for l in native["linkers"]), "foreign Cargo or linker")
    need(native["full"].count("zmij")==sum(not z["fresh"] for z in zmij), "typed/physical zmij mismatch")
    links=collections.Counter(output_name(l) for l in native["linkers"])
    binaries={}
    e2e=None
    e2e_links=None
    for r in units:
        if not r["executable"] or not r["profile"]["test"]:
            continue
        path=Path(r["executable"]).resolve(strict=True)
        key=(r["package_id"],r["target"]["name"],tuple(r["target"]["kind"]),str(path))
        need(str(path) not in binaries,"duplicate typed native executable path")
        binaries[str(path)]={"unit":key[:-1],"bytes":path.stat().st_size,"sha":sha(path),"links":links[str(path)]}
        if Path(r["target"]["src_path"]).resolve()==(repo/E2E).resolve():
            need(e2e is None,"ambiguous ty_server e2e")
            e2e=actual_tests(path,repo,env,state,dest)
            e2e_links=links[str(path)]
            if label in ("cold","edit","clean","repair") and "ty-comparison" in dest.parts:
                archive=root/"receipts/clean-ty-executables"/(e2e["raw"]+".macho.gz")
                if not archive.exists():
                    archive.parent.mkdir(exist_ok=True)
                    compress_bytes(archive,path.read_bytes())
    if ok:
        need(e2e is not None, "missing qualified ty_server e2e")
        if label=="edit":
            need(e2e_links==1,"real e2e edit did not physically relink the returned executable")
    else:
        need(any(r.get("message",{}).get("code") and r["message"]["code"]["code"]=="E0425"
                 for r in stream) and ERROR.encode() in stdout,"wrong invalid diagnostic")
        need(e2e is None, "invalid edit returned an e2e executable")
    save(dest/"verified.json",{"scope":scope,"state":state,"label":label,"argv":argv,"exit":code,
         "native":native,"typed":len(units),"dirty":sorted(r["target"]["name"] for r in units if not r["fresh"]),
         "binary_roster":binaries,"link_outputs":dict(links),"e2e_links":e2e_links,"e2e":e2e,
         "streams":clock["streams"],"scores":0})
    print(scope,label,"typed",len(units),"full",len(native["full"]),"link-only",len(native["link_only"]),
          "all ld",len(native["linkers"]),"tracked tests",len(binaries),
          "linked tests",sum(bool(v["links"]) for v in binaries.values()),"e2e",e2e_links,flush=True)
    if scope=="focus" and "ty-comparison" in dest.parts and label in ("cold","edit","repeat-1","repeat-2"):
        from ty_disk import snapshot
        snapshot(work, dest)
    return e2e


def run_focus(root, trace, role="S"):
    repo=root/"ruff"
    work=root/"ty-focus-work"
    work.mkdir(exist_ok=True)
    sdk=select(root,role)
    env=env_for(work,sdk)
    prefix=(root/"receipts/ty-focus" if role=="S" else root/"receipts/ty-comparison"/role/"focus")
    def visit(where, plan):
        check_host(root,24)
        fresh(work,root/"seed")
        ident=sdk_id(sdk,env)
        rows={}
        prev=None
        for label,state in plan:
            if state!=prev:
                checkout(repo,state)
            rows[label]=collect(root,"focus",work,sdk,env,trace,where/label,state,label)
            prev=state
        need(ident==sdk_id(sdk,env),"SDK drift")
        retire(work)
        return rows
    references={}
    for state in ("old","new"):
        references[state]=visit(prefix/("empty-"+state),[("clean",state)])["clean"]
    old,new=(set(references[k]["inventory"]) for k in ("old","new"))
    need(new-old=={NEW} and not old-new and references["old"]["raw"]!=references["new"]["raw"], "unexpected historical test inventory change")
    plan=[("cold","old"),("edit","new"),("repeat-1","new"),("repeat-2","new"),("invalid","bad"),("repair","new")]
    rows=visit(prefix/"visit", plan)
    comparisons={}
    for key,state in plan:
        if state=="bad":
            continue
        comparisons[key]={k:rows[key][k]==v for k,v in references[state].items()}
        need(all(comparisons[key].values()), "focused test executable differs from clean")
    save(prefix/"result.json",{"source":[A,B],"clean":references,"comparisons":comparisons,"scores":0})
    return references


def workspace(root,trace):
    # The full graph uses its own empty target and shared layout. This stage is an
    # unscored parent-only inventory; an identical output alone cannot authorize reuse.
    repo=root/"ruff"
    work=root/"ty-workspace-work"
    work.mkdir()
    sdk=select(root,"S")
    env=env_for(work,sdk)
    fresh(work,root/"seed")
    check_host(root,65)
    checkout(repo,"new")
    prefix=root/"receipts/ty-workspace"
    identity=sdk_id(sdk,env)
    rows={}
    for phase in ("cold","repeat-1","repeat-2"):
        check_host(root,15)
        rows[phase]=collect(root,"workspace",work,sdk,env,trace,prefix/phase,"new",phase)
    comparisons={phase:{k:v==rows["cold"][k] for k,v in row.items()} for phase,row in rows.items()}
    save(prefix/"result.json",{"source":B,"scores":0,"case":NEW,"clean_comparisons":comparisons,
                               "purpose":"signed same-graph link census"})
    need(all(c["inventory"] for c in comparisons.values()) and identity==sdk_id(sdk,env), "workspace test inventory or SDK changed")
    retire(work)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("seed","focus","workspace"))
    p.add_argument("root",type=Path)
    args=p.parse_args()
    root=args.root.resolve(strict=True)
    if args.mode=="seed":
        prepare_ruff(root,A,B,enrolled)
    else:
        need((root/"receipts/observer.json").is_file(),"Mac kernel capture required")
        trace=CensusTrace()
        try:
            trace.ready()
            (run_focus if args.mode=="focus" else workspace)(root,trace)
        finally:
            trace.close()
