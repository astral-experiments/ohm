"""Open one matched source SDK and repeat the two real unmodified Ruff consumer histories."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess as sp
import sys
import traceback

here = Path(__file__).resolve().parent
checkout = Path(os.environ["GITHUB_WORKSPACE"])
sys.path.insert(0, str(here))
import kits

baseline = checkout / "original/scripts/ruff-clap-reverse-metadata"
assert hashlib.sha256((baseline/"study.py").read_bytes()).hexdigest() == "275b03458ab8b0497c073674371aec082c60bb12ee2731f40ee57f88ef864a9f"
assert sp.check_output(["git","-C",baseline,"rev-parse","HEAD"],text=True).strip() == "e3bd205a4d90cacffb4daad102495c2d8e0242a1"
sys.path.insert(0, str(baseline))
import study as s
b = s.b
role = os.environ["ROLE"]
assert role in ("P","C")
role_name = {"P":"parent","C":"candidate"}[role]
assert os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["GITHUB_REF_NAME"]=="charlie/qa-ruff-clap-ctfe-reverse-20261104"
assert sp.check_output(["git","-C",here,"rev-parse","HEAD"],text=True).strip()==os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"]
assert sp.check_output(["git","-C",s.legacy,"rev-parse","HEAD"],text=True).strip()=="e48abf3b09f415b296d0ee2e8ec81c0de7b50611"
b.ROOT.mkdir(); b.guard(); s.OUT.mkdir()
cache=b.ROOT/"downloaded"
tar, proof=kits.fetch(role, cache, s.OUT/"factory")
kits.install(tar, proof, b.SDK, b.RUSTUP/"toolchains/ohm")
s.DRIVER = proof["driver"]
versions={n:sp.check_output([n,"+ohm","-vV"],env=b.env(),text=True)for n in ("rustc","cargo")}
assert versions==proof["versions"]
s.ver=versions["rustc"].splitlines()[0]+" (Ohm metadata 3)"
sp.run(["cc","-O2","-pthread","-Wall","-Wextra","-Werror",s.legacy/"exec_count.c","-o",b.ROOT/"exec_count"],check=True)
b.put(s.OUT/"registration.json", dict(role=role, source=kits.REGISTER[role_name],driver=s.DRIVER,original=kits.KIT[role],source_edit=[b.OLD,b.NEW],instrumentation="fixed exec/process witness only",boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()))
original_verdict=s.verdict

def native(dst, consumer):
    evidence=original_verdict(dst,consumer)
    store=s.OUT/"native-bodies"
    assert b.zsave(Path(evidence["path"]),store)==evidence["sha256"]
    if consumer=="ruff":
        tree=b.ROOT/"format-project";tree.mkdir(exist_ok=True);(tree/"out").mkdir(exist_ok=True)
        (tree/"ruff.toml").write_text('extend-exclude = ["out"]\n[format]\nexclude = ["format_excluded.py"]\n')
        for name in ("main.py","format_excluded.py","cli_excluded.py","out/a.py"):(tree/name).write_text("x    = 1\n")
        arg=["format","--check","--config","ruff.toml","--extend-exclude","cli_excluded.py","."]
        p=sp.run([evidence["path"],*arg],cwd=tree,env=b.env()|{"NO_COLOR":"1","COLUMNS":"240","LC_ALL":"C","TERM":"dumb","RUFF_NO_CACHE":"true"},capture_output=True)
        (dst/"changed-CLI.stdout").write_bytes(p.stdout);(dst/"changed-CLI.stderr").write_bytes(p.stderr)
        state=b.git("rev-parse","HEAD")
        if state==b.NEW:
            assert p.returncode==1 and b"main.py"in p.stdout and all(x not in p.stdout for x in (b"cli_excluded.py",b"format_excluded.py",b"out/a.py")) and b"Would reformat:" in p.stdout
        else:
            assert state==b.OLD and p.returncode==2 and b"--extend-exclude" in p.stderr
        b.put(dst/"changed-CLI.json",dict(sha256=evidence["sha256"],state=state,argv=arg,status=p.returncode))
    return evidence

s.verdict=native
def clear_project():
    for path in (b.TARGET,b.BUILD,b.HOME):
        if path.exists():
            assert path.parent==b.ROOT and path.is_dir() and not path.is_symlink()
            shutil.rmtree(path)

failures={}
try:
    sp.run([sys.executable,"-IB",here/"probe.py",s.OUT/"local-probes",here/"fixture",b.RUSTUP,role_name],check=True,env=b.env())
except Exception:
    failures["pointer-guard"]=traceback.format_exc();b.put(s.OUT/"refusals.json",failures);print(failures["pointer-guard"],flush=True)
finally:
    # The copied pointer oracle builds tiny private workspaces. Keep only the checked results.
    for name in ("fixture","cargo"):
        child=s.OUT/"local-probes"/name
        if child.is_dir():shutil.rmtree(child)

b.select(b.OLD);b.prepare()
choices={name:(client,prod)for name,client,prod in s.commands()}
assert set(choices)=={"ruff","ruff_dev"}
for name in ("ruff_dev","ruff"):
    try:
        clear_project();b.guard()
        result=s.run_lane("normal-"+name,name,*choices[name],False)
        assert result["initial_native"]==result["final_native"]
        assert result["definitions"][2] and result["expansions_equal"] and result["required_crates_equal"]
        label=s.OUT/("normal-"+name)
        sy,tabs=s.try_schema()
        phases={n:s.rows_at(label/n,sy,tabs) for n in ("initial-consumer","producer-NEW","producer-REPAIR","producer-OLD","unchanged-consumer")}
        p={n:v[0]for n,v in phases.items()}
        assert p["initial-consumer"]["public"]!=p["producer-NEW"]["public"] and p["producer-OLD"]==p["unchanged-consumer"]
        b.put(label/"all-publications.json",p)
        raw=s.read(label/"unchanged-consumer"/"real-compiler.json");evidence=[(r["crate"],r["kind"],any(a in ("link-only","-Zlink-only") for a in r["argv"]))for r in raw]
        b.put(label/"actual-changed-client.json",evidence)
    except Exception:
        failures[name]=traceback.format_exc();b.put(s.OUT/"refusals.json",failures);print(failures[name],flush=True)
if "ruff" not in failures:
    try:
        b.select(b.NEW);client,_=choices["ruff"];programs={}
        for key in ("warm-new","empty-new"):
            d=s.OUT/key
            if key=="empty-new":clear_project();b.guard();b.prepare()
            r=s.command(d,client);assert any(x["crate"]=="ruff" and x["kind"]=="bin" for x in r)
            files=s.selected(r,"ruff");s.snapshot(d,files,True);programs[key]=native(d,"ruff")
        assert programs["warm-new"]==programs["empty-new"]
    except Exception:
        failures["independent-new"]=traceback.format_exc();b.put(s.OUT/"refusals.json",failures);print(failures["independent-new"],flush=True)
b.put(s.OUT/"terminal.json",dict(role=role,completed=not failures,discovery_ordinary_only=True,failures=failures))
if failures:raise RuntimeError(failures)
