"""Measure the two pinned uv edits against three release-configured compilers."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import random
import re
import resource
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import tomllib

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "protocol.json").read_bytes())
PINS = json.loads((HERE / "arms.json").read_bytes())
ARMS = P["arms"]
WORK = Path(os.environ["RUNNER_TEMP"]) / "rc23-trait-work"
W = Path(os.environ["GITHUB_WORKSPACE"])
EVIDENCE = W / "trait-results"
SDK = WORK / "active-sdk"
SLOT = WORK / "slot"
UV = W / "uv-src"
DEPS = WORK / "registry-home"


def check(condition, text):
    if not condition:
        raise RuntimeError(text)


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def switch(arm):
    SDK.unlink(missing_ok=True)
    SDK.symlink_to(WORK / ("sdk-" + arm), target_is_directory=True)


def git(*args, data=None):
    return subprocess.check_output(["git", "-C", UV, *args], input=data)


def environment():
    return dict(PATH=f"{(WORK / 'bin')}:{SDK / 'bin'}:/usr/bin:/bin", HOME=str(SLOT / "home"),
                TMPDIR=str(SLOT / "tmp"), CARGO_HOME=str(SLOT / "cargo"), CARGO_TARGET_DIR=str(SLOT / "target"),
                CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never", RUSTC=str(SDK / "bin/rustc"),
                RUSTDOC=str(SDK / "bin/rustdoc"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="file", LC_ALL="C")


def install():
    ids = {}
    for arm in ARMS:
        media = W / "sdk-media" / ("rc23-trait-sdk-" + arm)
        source = json.loads((media / "source.json").read_bytes())
        check(source["workflow"] == P["build_head"] and int(source["run"]) == P["build_run"] and
              source["arm"] == arm and source["source"] == PINS["arms"][arm], f"wrong {arm} source receipt")
        check(source["manifest"]["sources"]["cargo"]["revision"] == PINS["cargo"] and
              source["base_manifest_sha256"] == PINS["source_manifest_sha256"], "unexpected release inputs")
        archive = media / "ohm.tar.gz"
        archive_hash = sha(archive)
        check((media / "SHA256SUMS").read_text().split() == [archive_hash, "ohm.tar.gz"], f"{arm} SDK checksum")
        tmp = WORK / "unpack"
        tmp.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        root = tmp / ("rust-1.99.0-dev-" + P["target"])
        check(list(tmp.iterdir()) == [root], "unexpected SDK layout")
        sdk = WORK / ("sdk-" + arm)
        subprocess.run([root / "install.sh", "--prefix=" + str(sdk), "--disable-ldconfig",
                        "--components=rustc,cargo,rust-std-" + P["target"]], check=True)
        shutil.rmtree(tmp)
        version = subprocess.check_output([sdk / "bin/rustc", "-vV"], text=True)
        check("commit-hash: " + PINS["arms"][arm]["rust"] in version and
              "host: " + P["target"] in version, f"unexpected {arm} compiler: {version}")
        check(Path(subprocess.check_output([sdk / "bin/rustc","--print","sysroot"],text=True).strip()).resolve() == sdk,
              "unexpected sysroot")
        ldd = subprocess.check_output(["ldd", sdk / "bin/rustc"], text=True)
        libs = {}
        for kind in ("librustc_driver", "libLLVM"):
            matches = [Path(p).resolve(strict=True) for name,p in re.findall(r"^\s*(\S+) => (\S+)",ldd,re.M)
                       if name.startswith(kind)]
            check(len(matches) == 1 and matches[0].is_relative_to(sdk), f"unexpected loaded {kind}")
            libs[kind] = sha(matches[0])
        ids[arm] = {"source":source,"archive_sha256":archive_hash,"rustc":version,"libraries":libs,
                    "rustc_sha256":sha(sdk/"bin/rustc"),"cargo_sha256":sha(sdk/"bin/cargo"),
                    "cargo":subprocess.check_output([sdk/"bin/cargo","-Vv"],text=True)}
    check(len({v["libraries"]["librustc_driver"] for v in ids.values()}) == 3, "identical compiler drivers")
    check(len({tuple(sorted(v["source"]["scripts"].items())) for v in ids.values()}) == 1, "different build scripts")
    save(EVIDENCE / "installed.json", ids)
    (WORK / "bin").mkdir()
    (WORK / "bin/cargo").symlink_to(WORK / "sdk-base/bin/cargo")


def cpus():
    allowed = sorted(os.sched_getaffinity(0))
    cores = {}
    for n in allowed:
        t = Path(f"/sys/devices/system/cpu/cpu{n}/topology")
        key = tuple((t / v).read_text().strip() for v in ("physical_package_id","core_id"))
        cores.setdefault(key,n)
    selected = (list(cores.values()) if len(cores) >= P["jobs"] else allowed)[:P["jobs"]]
    check(len(selected) == P["jobs"], "runner exposes too few CPUs")
    os.sched_setaffinity(0,selected)
    save(EVIDENCE / "host.json", {"cpu":subprocess.check_output(["lscpu","--json"],text=True),
         "uname":platform.uname()._asdict(),"allowed_before":allowed,"selected":selected,
         "cpu_max":Path("/sys/fs/cgroup/cpu.max").read_text() if Path("/sys/fs/cgroup/cpu.max").exists() else None})
    return sorted(selected)


def orders(case):
    out = []
    for seed in case["seeds"]:
        rows = list(itertools.permutations(ARMS))
        random.Random(seed).shuffle(rows)
        out.extend(rows)
    return out


def fetch(case):
    git("checkout","--quiet","--detach",case["parent"])
    check(git("rev-parse",case["child"]+"^").decode().strip() == case["parent"], "wrong uv history")
    delta = git("diff","--binary","--full-index","--no-ext-diff",case["parent"],case["child"])
    check(hashlib.sha256(delta).hexdigest() == case["patch"], "wrong uv patch")
    (EVIDENCE / (case["name"]+".patch")).write_bytes(delta)
    env = os.environ.copy()
    for name in list(env):
        if name.startswith(("CARGO_","RUST","OHM_","SCCACHE_")):
            del env[name]
    env.update(CARGO_HOME=str(DEPS), RUSTC=str(WORK/"sdk-base/bin/rustc"), CARGO_NET_RETRY="3")
    subprocess.run([WORK/"sdk-base/bin/cargo","fetch","--locked"],cwd=UV,env=env,check=True)
    packages = tomllib.loads((UV/"Cargo.lock").read_text())["package"]
    for pkg in packages:
        if pkg.get("source","").startswith("registry+"):
            candidates = list((DEPS/"registry/cache").glob(f"*/{pkg['name']}-{pkg['version']}.crate"))
            check(any(sha(f) == pkg["checksum"] for f in candidates), f"missing locked crate {pkg['name']}")
    return delta


def command(log, phase, mask, case):
    argv = [str(WORK/"bin/cargo"),*P["command"]]
    check(sorted(os.sched_getaffinity(0)) == mask, "affinity changed")
    def cpu_lines():
        wanted = {f"cpu{i}" for i in mask}
        return [s for s in Path("/proc/stat").read_text().splitlines() if s.split()[0] in wanted]
    before = cpu_lines()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic_ns()
    p = subprocess.run(argv,cwd=UV,env=environment(),capture_output=True)
    end = time.monotonic_ns()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (log/(phase+".stdout")).write_bytes(p.stdout)
    (log/(phase+".stderr")).write_bytes(p.stderr)
    dirty = sorted(n.decode() for n in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v",p.stderr,re.M))
    row = {"argv":argv,"start_ns":start,"end_ns":end,"ns":end-start,"exit":p.returncode,"dirty":dirty,"cpus":mask,
           "cpu_before":before,"cpu_after":cpu_lines(),"user_s":after.ru_utime-usage.ru_utime,
           "system_s":after.ru_stime-usage.ru_stime,"stdout_sha256":hashlib.sha256(p.stdout).hexdigest(),
           "stderr_sha256":hashlib.sha256(p.stderr).hexdigest()}
    save(log/(phase+".json"),row)
    check(p.returncode == 0, f"{case['name']} {phase} failed: {p.stderr.decode(errors='replace')[-1400:]}")
    if phase.startswith("unchanged"):
        check(not dirty,f"{phase} unexpectedly recompiled {dirty}")
    elif phase == "cold":
        check("uv-resolver" in dirty,"cold check skipped uv-resolver")
    else:
        check(case["affected"] in dirty,f"changed crate missing from first-edit roster {dirty}")
    return row


def trial(case, delta, arm, number, mask, output):
    switch(arm)
    for name in ("home","tmp","cargo"):
        (SLOT/name).mkdir(parents=True)
    for name in ("registry","git"):
        if (DEPS/name).exists():
            (SLOT/"cargo"/name).symlink_to(DEPS/name,target_is_directory=True)
    git("reset","--quiet","--hard",case["parent"])
    check(not git("status","--porcelain"),"uv parent is dirty")
    log = output / f"{number}-{arm}"
    log.mkdir()
    rows = {}
    for phase in P["phases"]:
        if phase == "first-edit":
            git("apply","--index","-",data=delta)
            check(git("write-tree") == git("rev-parse",case["child"]+"^{tree}"),"edited uv tree differs")
            git("reset","--quiet","--mixed",case["parent"])
            check(git("diff","--binary","--full-index","--no-ext-diff","HEAD") == delta,"unstaged edit differs")
        rows[phase] = command(log,phase,mask,case)
    shutil.rmtree(SLOT)
    return rows


def summarize(case, output):
    result = {}
    for phase in P["phases"]:
        rows = [{a:json.loads((output/f"{n:02}-{a}"/(phase+".json")).read_bytes()) for a in ARMS}
                for n in range(1,len(orders(case))+1)]
        for row in rows:
            check(len({tuple(v["dirty"]) for v in row.values()})==1, "rebuild rosters differ; inspect the raw evidence")
        section = {"median_seconds":{a:statistics.median(r[a]["ns"] for r in rows)/1e9 for a in ARMS}}
        for before,after in P["comparisons"]:
            gains = [100*(1-r[after]["ns"]/r[before]["ns"]) for r in rows]
            ranked = sorted(gains)
            section[f"{before}_to_{after}"] = {"paired_percent_reduction":statistics.median(gains),
                        "median_interval_96.14_percent":[ranked[2],ranked[-3]],"wins":sum(v>0 for v in gains),
                        "cohort_medians":[statistics.median(gains[:6]),statistics.median(gains[6:])]}
        result[phase] = section
    save(output/"summary.json",result)


def main():
    check(platform.system()=="Linux" and platform.machine()=="x86_64","wrong host")
    check(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_EVENT_NAME"]=="workflow_dispatch" and
          os.environ["GITHUB_REF"]=="refs/heads/charlie/codex-rc23-trait-qualification" and
          os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"], "unexpected workflow")
    WORK.mkdir()
    EVIDENCE.mkdir()
    shutil.copyfile(HERE/"protocol.json",EVIDENCE/"protocol.json")
    mask = cpus()
    install()
    subprocess.run([sys.executable,"-IB",HERE/"native-checks.py",WORK,EVIDENCE,W/"sdk-media"/"rc23-trait-sdk-both"/"fixture"],check=True)
    for case in P["cases"]:
        out = EVIDENCE/case["name"]
        out.mkdir()
        delta = fetch(case)
        save(out/"orders.json",orders(case))
        for arm in ARMS:
            trial(case,delta,arm,"excluded-warmup",mask,out)
        for n, group in enumerate(orders(case),1):
            for arm in group:
                trial(case,delta,arm,f"{n:02}",mask,out)
            print(f"{case['name']}: {n}/{len(orders(case))} triples",flush=True)
        summarize(case,out)
        git("reset","--hard",case["parent"])
    save(EVIDENCE/"completed.json",{"build":P["build_run"],"run":os.environ["GITHUB_RUN_ID"],
         "attempt":os.environ["GITHUB_RUN_ATTEMPT"],"sha":os.environ["GITHUB_SHA"],
         "summaries":{c["name"]:sha(EVIDENCE/c["name"]/"summary.json") for c in P["cases"]}})


if __name__=="__main__":
    main()
