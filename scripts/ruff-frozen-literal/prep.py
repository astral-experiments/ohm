"""Authenticate the complete source-built SDK and both unmodified historical Ruff checkouts."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-module-16149"))
import setup as old

w = old.w
REG = json.loads((HERE / "registration.json").read_bytes())
BIND = json.loads((HERE / "factory.json").read_bytes())
A, B = (REG["source"][k] for k in ("A", "B"))
ROOT = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ohm-frozen-29042"
BASE = ROOT / "receipt"
w.ROOT, w.OUT, w.SDK, w.STATE, w.BRANCH = ROOT, BASE, ROOT/"sdk", ROOT/"state", REG["branch"]
old.BASE_OUT = BASE
need, save, sha = w.need, w.save, w.sha
env, activate = old.env, old.activate
OBS = HERE.parent / "ruff-heldout-mono-fold/residual/exec_count.c"
WHOLE = HERE.parent / "ruff-ruf009-derived-enum/whole_count.c"
CHECK = REG["target"]
PARSER = REG["common_symbol_guard"]
NATIVE = [*CHECK[:2], "build", *CHECK[3:], "--message-format=json"]
INVALID = b'\nconst OHM_FROZEN_LITERAL_INVALID: u32 = "invalid";\n'


def source(revision):
    need(revision in (A, B), "unknown Ruff state")
    need(not w.git(w.SRC, "status", "--porcelain", "--untracked-files=all"), "changed ordinary source")
    if w.git(w.SRC, "rev-parse", "HEAD") != revision:
        subprocess.run(["git", "-C", w.SRC, "checkout", "--quiet", "--detach", revision], check=True)
    need(w.git(w.SRC,"rev-parse","HEAD","HEAD^{tree}").splitlines() == [revision,REG["trees"][revision]]
         and not w.git(w.SRC,"status","--porcelain","--untracked-files=all")
         and sha(w.SRC/"Cargo.lock") == REG["source"]["lock_sha256"], "different historical source")


def pin_cpus():
    available = sorted(os.sched_getaffinity(0))
    cpus = available[:4]
    need(len(cpus) == 4, "four original CPUs required")
    os.sched_setaffinity(0, cpus)
    return cpus


def expected(role):
    packed = gzip.decompress((HERE/"members.json.gz").read_bytes())
    need(hashlib.sha256(packed).hexdigest() == REG["member_map_sha"], "different reference ZIP members")
    data = json.loads(packed)
    return data["rows"] if role == "old" else data["rows"] | data["edit"]


def acquire():
    w.checked_head()
    need(not ROOT.exists(), "worker reused")
    ROOT.mkdir(); BASE.mkdir(); (BASE/"objects").mkdir()
    need(w.resources()[1] > 35*(1<<30), "initial disk reserve")
    source(B); source(A); source(B)
    need(w.git(w.SRC,"rev-parse",B+"^") == A and w.git(w.SRC,"diff","--name-only",A,B).splitlines() == REG["files"], "not the registered Ruff change")
    need(len(expected("old")) == len(expected("new")) == REG["expected_member_count"], "ZIP reference inventory")
    info = old.api("actions/runs/"+os.environ["GITHUB_RUN_ID"])
    jobs = old.api(f"actions/runs/{info['id']}/attempts/1/jobs?per_page=100")
    job, = jobs["jobs"]
    cpus = pin_cpus()
    need(jobs["total_count"] == 1 and job["name"] == "Ruff literal edit and parser control" and job["runner_name"] == os.environ["RUNNER_NAME"] and job["runner_id"] > 0 and info["head_sha"] == os.environ["REVIEWED_HEAD"] and info["head_branch"] == w.BRANCH and info["run_attempt"] == 1, "unregistered worker")
    save(BASE/"worker.json",dict(run=info["id"],job=job["id"],runner=job["runner_name"],runner_id=job["runner_id"],head=info["head_sha"],boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),cpus=cpus,registration=REG,factory=BIND,resources=w.resources(),observers=[sha(OBS),sha(WHOLE)]))
    kit = old.scope_matched.kit("frozen",BIND)
    roles = {}
    with zipfile.ZipFile(ROOT/"scope-kit-frozen/receipts.zip") as z:
        need(b"test symbol::tests::large_strings_keep_their_bytes_and_share_symbol_ids ... ok" in z.read("symbol-C.log") and b"1 passed; 0 failed; 0 ignored" in z.read("run-make-C.log") and set(json.loads(z.read("literal-epochs.json"))) == {"PC","CP"}, "full compiler safety input absent")
        for role,label,name in (("P","parent","normal"),("C","candidate","defer")):
            guard = json.loads(z.read("scope-guard-"+label+".json")); sdk=Path(kit["arms"][name]["root"]);driver,=(sdk/"lib").glob("librustc_driver-*.so")
            need(guard["role"] == label and "middle-edit" in guard["cases"] and "uninitialized" in guard["cases"] and guard["driver_sha256"] == sha(driver), "different checked compiler")
            roles["inline-"+role] = dict(source=BIND["source"][role],sdk=str(sdk),driver=sha(driver),rustc=sha(sdk/"bin/rustc"),cargo=sha(sdk/"bin/cargo"),files=kit["arms"][name]["files"])
    need(roles["inline-P"]["driver"] != roles["inline-C"]["driver"] and roles["inline-P"]["cargo"] == roles["inline-C"]["cargo"],"unmatched core")
    save(BASE/"scope-sdks.json",roles)
    (ROOT/"proxies").mkdir(); system=Path(shutil.which("rustup")).resolve(strict=True); shutil.copy2(system,ROOT/"proxies/rustup")
    for name in ("cargo","rustc","rustdoc"):(ROOT/"proxies"/name).symlink_to("rustup")
    for name in ("home","temp","cargo","rustup/toolchains"):(ROOT/name).mkdir(parents=True)
    (ROOT/"rustup/toolchains/ohm").symlink_to(w.SDK)
    (ROOT/"rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    activate("P")
    state=env();state.pop("CARGO_NET_OFFLINE")
    w.run(["cargo","+ohm","fetch","--locked"],state,BASE/"fetch")
    packages=tomllib.loads((w.SRC/"Cargo.lock").read_text())["package"]
    expected_registry={}
    cache,=[p for p in (ROOT/"cargo/registry/cache").iterdir()if p.is_dir()]
    for p in packages:
        if "source" not in p:continue
        n,v=p["name"],p["version"];name=n+"-"+v+".crate";digest=p["checksum"]
        need(p["source"]=="registry+https://github.com/rust-lang/crates.io-index" and re.fullmatch("[a-zA-Z0-9_-]+",n) and re.fullmatch("[0-9a-zA-Z.+-]+",v) and name not in expected_registry,"unexpected source or duplicate")
        expected_registry[name]=digest
        if not (cache/name).exists():
            with urllib.request.urlopen(f"https://static.crates.io/crates/{n}/{name}",timeout=45) as response:buf=response.read((64<<20)+1)
            need(0<len(buf)<=64<<20 and hashlib.sha256(buf).hexdigest()==digest,"wrong supplemental registry source")
            with (cache/name).open("xb")as f:f.write(buf)
    files=list((ROOT/"cargo/registry/cache").glob("*/*.crate"));actual={f.name:sha(f)for f in files}
    need(len(files)==len(actual)==REG["registry_archives"] and actual==expected_registry,"complete 505-archive lock custody")
    save(BASE/"registry.json",actual); (ROOT/"cargo").rename(ROOT/"prefetched-cargo")
    observer_source=OBS.read_text()
    anchor="int main(int argc,char **argv) {"
    exit_hook="if(event==PTRACE_EVENT_EXIT)checkpoint(t);"
    need(observer_source.count(anchor)==observer_source.count(exit_hook)==1,"different original observer source")
    joined=ROOT/"owner-count.c"
    joined.write_text(observer_source.replace(anchor,(HERE/"driver_maps.inc").read_text()+"\n"+anchor).replace(exit_hook,"if(event==PTRACE_EVENT_EXIT){checkpoint(t);driver_at_exit(t);}"))
    need(sha(joined)==REG["compiled_observer_source"],"unregistered read-only image observer")
    for code,binary in ((joined,"exec-count"),(WHOLE,"whole-count")):
        subprocess.run(["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror",code,"-o",ROOT/binary],check=True)
    save(BASE/"environment.json",env())
