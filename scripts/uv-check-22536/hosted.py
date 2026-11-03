"""Run the existing #22536 native/measurement stages with the admitted release-23 media."""
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release23 as rel

REPO = "astral-experiments/ohm"
REPO_ID = 1319437234
BRANCH = "charlie/codex-22536-signed23-projection"
BASE = "ca8b83712b881b45cbb8e8b0513d0811971e4a98"
PRIMARY_BASE = "8b2ffa46cb0b3d37188f7c286048865237ff6128"
PAIRED = "eight-real-session-pairs"
COORDINATOR_KIT = "scripts/uv-check-22536"
PRIMARY_KIT = "scripts/uv-client-22958"
DONOR = "8bf1d2c61fa3bb23ccf44a329e74e0359d98848c"
DONOR_SHA = "88bf7f852c5616c2b09d395fd4cb662a3c6303c79f8e8866dee25bee621be57f"
PACKAGE_SHA = "7481bffd4b25e63ba1496f1781fe44898c35a60b0d783da03b477879e9f19f66"
INTAKE_SHA = "d147920c7806591fd15d7ae4d26e32f472bb37ac464a6e85d9e29ede0faf2856"
DYNAMIC = {".github/workflows/ci.yml"} | set(COORDINATOR_KIT + "/" + n for n in ("release23-inputs.json", "hosted-inputs.json", "SHA256SUMS"))


def filehash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("xb") as dest:
        dest.write(rel.canon(value) + b"\n")


def git(path, *args):
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="file", GIT_OPTIONAL_LOCKS="0")
    return subprocess.check_output(["git", "-C", str(path), *args], env=env, text=True).strip()


def active_binding():
    active = rel.lock()
    source = rel.read(HERE / "hosted-inputs.json")
    population = rel.read(HERE / "registration.json")["source_population"]
    assert (active["release"]["tag"],active["release"]["rustc"],active["release"]["cargo"]) == (population["release_tag"],population["rust"],population["cargo"])
    assert active["roles"]["R"]["source"] == {"commit":population["rust"],"tree":population["tree"],"epoch":26655,"metadata_epoch":3}
    assert set(active["roles"]) == ({"R","F"} if active["full_variant"] == "full_without_ctfe" else {"R","S","F"})
    assert active["full_variant"] in ("full_with_ctfe","full_without_ctfe")
    assert source["registration"] == rel.REGISTRATION
    assert source["input_sha256"] == filehash(HERE / "release23-inputs.json")
    assert source["primary_lock"] == active["primary_lock_sha256"] and source["primary_choice"] == active["primary_choice_sha256"]
    assert source["primary_native_score"] and source["primary_outer"]["digest"].startswith("sha256:")
    assert source["completed_22_sha256"] == "a35ca64f0b2bc928a66cc4ecdaead56345ea454e1a2f1abbe5e21bc90cc9b21a"
    return active, source


def scope(active, source):
    e = os.environ
    assert e["GITHUB_ACTIONS"] == "true" and e["GITHUB_REPOSITORY"] == REPO and e["GITHUB_REPOSITORY_ID"] == str(REPO_ID)
    ref = "refs/heads/" + BRANCH
    assert e["GITHUB_EVENT_NAME"] == "workflow_dispatch" and e["GITHUB_REF"] == ref and e["GITHUB_RUN_ATTEMPT"] == "1"
    assert e["GITHUB_WORKFLOW_REF"] == REPO + "/.github/workflows/ci.yml@" + ref
    w, temp = (Path(e[k]).resolve(strict=True) for k in ("GITHUB_WORKSPACE", "RUNNER_TEMP"))
    co, other = w / "coordinator", w / "primary-coordinator"
    assert HERE == co / COORDINATOR_KIT and e["REVIEWED_HEAD"] == git(co, "rev-parse", "HEAD") == e["GITHUB_SHA"]
    assert git(co, "rev-parse", "HEAD^") == source["carrier"] and git(co, "rev-parse", "HEAD^^") == BASE
    assert set(git(co, "diff", "--name-only", "--no-renames", "HEAD^", "HEAD").splitlines()) == DYNAMIC
    original=git(co,"show","HEAD^:.github/workflows/ci.yml")
    closed="github.run_attempt == 1 && false"
    enabled="github.run_attempt == 1 && inputs.enrollment_sha == '"+e["ENROLLMENT_SHA"]+"' && inputs.primary_head == '"+e["PRIMARY_HEAD"]+"'"
    assert original.count(closed)==1 and git(co,"show","HEAD:.github/workflows/ci.yml")==original.replace(closed,enabled)
    assert not git(co, "status", "--porcelain", "--untracked-files=no")
    assert filehash(HERE / "hosted-inputs.json") == e["ENROLLMENT_SHA"]
    assert e["PRIMARY_HEAD"] == source["primary_head"] == git(other, "rev-parse", "HEAD")
    assert not git(other, "status", "--porcelain", "--untracked-files=no")
    primary = other / PRIMARY_KIT
    assert filehash(primary / "signed-23-lock.json") == source["primary_lock"]
    assert filehash(primary / "signed-23-choice.json") == source["primary_choice"]
    assert filehash(primary / "release23_package.py") == PACKAGE_SHA and filehash(primary / "release_intake.py") == INTAKE_SHA
    assert git(w / "previous", "rev-parse", "HEAD") == DONOR
    assert filehash(w / "previous/scripts/uv-resolver-whole-pmu/intake.py") == DONOR_SHA
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert boot not in active["excluded"] and (set(source["additional_boots"]) <= set(active["excluded"]))
    assert str(e["RUNNER_NAME"]) not in {j["runner_name"] for j in source["excluded_jobs"]}
    return w, temp, primary, boot


def service_job(rows, run, head, runner, excluded):
    assert rows["total_count"] == len(rows["jobs"]) == 1
    job, = rows["jobs"]
    assert job["run_id"] == run and job["head_sha"] == head and job["run_attempt"] == 1 and job["name"] == PAIRED
    assert job["runner_name"] == runner and type(job["runner_id"]) is int and job["runner_id"] > 0
    assert job["status"] == "in_progress" and job["conclusion"] is None
    assert all(job["id"] != j["job"] and job["runner_id"] != j["runner_id"] and job["runner_name"] != j["runner_name"] for j in excluded)
    return {k:job[k] for k in ("id","run_id","head_sha","runner_name","runner_id","name","run_attempt")}


def current_job(donor, source, proof):
    run = int(os.environ["GITHUB_RUN_ID"])
    endpoint = f"repos/{REPO}/actions/runs/{run}/attempts/1/jobs?per_page=100"
    for n in range(24):
        rows = donor.gh_json("api", "--method", "GET", "-H", "Cache-Control: no-cache", endpoint)
        # A newly assigned job need not be visible on the first jobs-list read.
        if rows["total_count"] and all(j.get("runner_id") for j in rows["jobs"]):
            write(proof / "assigned-jobs.json", rows)
            return service_job(rows, run, os.environ["REVIEWED_HEAD"], os.environ["RUNNER_NAME"], source["excluded_jobs"])
        time.sleep(5)
    raise RuntimeError("Actions did not return the independently assigned physical runner")


def verify_host(root, active):
    source = rel.read(HERE / "hosted-inputs.json")
    measured = rel.read(root / "calibration/accepted.json")
    transport = rel.read(root / "transport.json")
    job = transport["assigned"]
    assert transport["boot"] == measured["boot"] and measured["boot"] not in active["excluded"]
    assert transport["host_inputs"] == filehash(root / "actual-inputs.json")
    assert len(measured["excluded"]) == len(active["excluded"]) >= 32
    assert set(measured["excluded"]) == set(active["excluded"]) and set(source["additional_boots"]) <= set(measured["excluded"])
    assert source["input_sha256"] == filehash(HERE / "release23-inputs.json")
    assert job["run_attempt"] == 1 and job["name"] == PAIRED
    assert re.fullmatch("[0-9a-f]{40}",job["head_sha"]) and job["runner_id"] > 0
    assert job["run_id"] != source["primary_original"]["run"] and job["head_sha"] != source["primary_head"]
    for previous in source["excluded_jobs"]:
        assert job["id"] != previous["job"] and job["runner_id"] != previous["runner_id"] and job["runner_name"] != previous["runner_name"]
    return job


def native_rosters(root, active):
    """Reopen every cold, edited and quiet Cargo kernel stream of the elected opening."""
    from basis import CASE, EVENTS, SIX, WUNITS, option, readz
    from collections import Counter
    materials=rel.read(root/"actual-inputs.json")
    assert set(materials)==set(active["roles"])
    gate=root/"qualification"
    control=rel.read(gate/"accepted.json")["control"]
    families={"signed-1":"R","treatment":"F"}
    if control=="S":
        families.update({"signed-2":"R","corrected":"S"})
    else:
        assert control=="R" and not (gate/"corrected").exists() and not (gate/"signed-2").exists()
    evidence={}
    for family,role in families.items():
        mat=materials[role]
        assert mat["signed_cargo"]==active["signed_cargo"]
        dr=gate/family
        visits={}
        for phase in ("cold-A","noedit-A",*(k+"-"+st for st in "BCD" for k in ("warm","noedit","fresh"))):
            folder=dr/phase
            packet=EVENTS["decode"](readz(folder/"kernel.json.gz"))
            native=readz(folder/"argv.json.gz")
            rootpid=packet["root"];first=packet["images"][0]
            assert first["pid"]==rootpid==native["root"] and packet["exits"][rootpid]==0
            assert first["file"]==mat["cargo_kernel_identity"] and first["argv"][1:]==["check","-p","uv-client","--locked","--offline","-j8"]
            ids={row["pid"] for row in packet["images"]}
            rustcs={row["pid"]:row for row in packet["images"]if row["file"]==mat["rustc_kernel_identity"]}
            assert not any(row["file"]!=mat["rustc_kernel_identity"] and Path(row["exe"]).name=="rustc" for row in packet["images"])
            emitted,probes=native["all_units"],native["all_other_rustcs"]
            assert sorted(rustcs)==sorted([row[1]for row in emitted]+[row[0]for row in probes])
            for name,pid,parent in emitted:
                argv=rustcs[pid]["argv"]
                ancestor=packet["births"][pid];seen=set()
                while ancestor not in ids:
                    assert ancestor not in seen;seen.add(ancestor);ancestor=packet["births"][ancestor]
                assert ancestor==parent==rootpid and packet["exits"][pid]==0
                assert option(argv,"--crate-name")==name and option(argv,"--emit") and argv in native["forms"][name]
            if phase.startswith(("cold-","fresh-")):
                assert len(emitted)==497 and len(probes)==45 and set(native["workspace_rmeta_from_argv"])==WUNITS
                assert dict(Counter(x[1]for x in probes))==CASE["expected"]["A"]["other"]
            elif phase.startswith("noedit-"):
                assert not rustcs and not native["forms"] and not native["workspace_rmeta_from_argv"]
            else:
                assert len(emitted)==6 and not probes and sorted(native["forms"])==SIX and all(len(v)==1 for v in native["forms"].values())
            visits[phase]={"emitting":len(emitted),"other_rustcs":len(probes),"workspace_rmeta":len(native["workspace_rmeta_from_argv"]),
                           "kernel_sha256":filehash(folder/"kernel.json.gz"),"argv_sha256":filehash(folder/"argv.json.gz")}
        evidence[family]={"role":role,"visits":visits}
    return evidence


def native_selection(root, active):
    return {"decision":rel.confirm_native(root,HERE,active),"actual_cargo_visits":native_rosters(root,active)}


def finish_setup(config_path, cfg, evidence):
    from basis import Env, setup
    results = Path(cfg["results"])
    assert results.is_dir() and not any(results.iterdir()) and not config_path.exists()
    setup(Env(cfg))
    assert {f.name for f in results.iterdir()} == {"actual-inputs.json","source-registry.json"}
    write(config_path, cfg)
    write(results / "transport.json", evidence | {"host_inputs": filehash(results / "actual-inputs.json")})


def acquire(active, source, w, t, primary, boot):
    import importlib.util
    spec = importlib.util.spec_from_file_location("original_public_and_actions_transport", w / "previous/scripts/uv-resolver-whole-pmu/intake.py")
    donor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(donor)
    proof, incoming, pool = w / "trait-results", t / "uv22536-release23-incoming", t / "ctfe22-root-sdks"
    for directory in (proof, incoming, pool):
        directory.mkdir()
    write(proof / "unscored-start.json", {"boot":boot, "source":os.environ["GITHUB_SHA"], "registration":rel.REGISTRATION})
    job = current_job(donor, source, proof)
    from installed_worker import latest
    latest(proof / "initial-publication.json", active["release"])
    assert min(shutil.disk_usage(d).free for d in (t,w)) >= 80 << 30
    sys.path.insert(0, str(primary))
    import release23_package as pkg
    assert Path(pkg.__file__).resolve() == primary / "release23_package.py"
    assert Path(pkg.sdk.__file__).resolve() == primary / "release_intake.py"
    lock = pkg.s.lock
    assert lock["signed_release"] == active["release"] and lock["signed_cargo"] == active["signed_cargo"]
    assert set(active["roles"]) == {"R", *lock["builders"]}
    signed = pkg.official(donor, proof, incoming)
    cargo = pkg.sdk.signed_cargo(signed, incoming / "actual-signed-cargo")
    installed = {}
    for role, row in active["roles"].items():
        rd = proof / ("role-" + role)
        rd.mkdir()
        if role == "R":
            archive = signed
            raw = row["runtime"]
            if "R" in lock["raw"]:
                assert raw == lock["raw"]["R"] and row["source"] == lock["sources"]["R"]
        else:
            assert lock["sources"][role] == row["source"]
            archive = pkg.production(role, donor, rd, incoming)
            raw = lock["raw"][role]
            assert dict(raw, **{"bin/cargo":active["roles"]["R"]["runtime"]["bin/cargo"]}) == row["runtime"]
        effective = rel.sha(rel.canon({n:r["sha256"] for n,r in row["runtime"].items()}))
        # The primary worker installs only S+F if #22958 needed its correction.
        # Admit the independent official R with its own signed manifest in that case.
        with patch.dict(lock["raw"], {role:raw}), patch.dict(pkg.s.SOURCES, {role:row["source"]}), patch.dict(lock["effective_hashes"], {role:effective}):
            dest = pool / role
            pkg.sdk.install_archive(archive, dest, role)
            assert filehash(dest / "bin/cargo") == raw["bin/cargo"]["sha256"]
            shutil.copy2(cargo, dest / "bin/cargo")
            installed[role] = pkg.sdk.role_sdk(role, dest, rd / "installed")
    complete = {"source_lock":source["primary_lock"], "primary_native_score":source["primary_native_score"],
                "registered":rel.REGISTRATION,"initial_publication":filehash(proof/"initial-publication.json"),
                "actual_sdk_files":installed,"job":job,"boot":boot,"role_choice":"pending #22536 native opening"}
    write(proof / "installed-23.json",complete)
    # All source build/test Cargos run in the clean own Env, and only this fetch
    # is allowed to populate the initially empty private registry.
    from basis import CASE
    uv = w / "uv-source"
    assert git(uv, "rev-parse", "HEAD") == CASE["states"]["D"]["source"]
    scan = t / "uv22536-registry"
    scan.mkdir()
    env = {"HOME":str(t),"PATH":str(pool/"R/bin")+":/usr/bin:/bin","CARGO_HOME":str(scan),
           "RUSTC":str(pool/"R/bin/rustc"),"GIT_TERMINAL_PROMPT":"0","LC_ALL":"C.UTF-8"}
    subprocess.run([pool/"R/bin/cargo","fetch","--locked"], cwd=uv, env=env, check=True)
    root, results = t / "uv22536-canonical", w / "session-results"
    root.mkdir()
    results.mkdir()
    cfg={"root":str(root),"results":str(results),"source_donor":str(uv),"sdks":{r:str(pool/r) for r in active["roles"]},
         "cargo_home":str(scan),"control_candidate_source_inputs":source["input_sha256"],"fresh_private_sdk_pool":str(pool),
         "require_source_tag":True,"excluded_boots":sorted(active["excluded"])}
    finish_setup(w / "session-config.json",cfg,{"transport":filehash(proof/"installed-23.json"),"assigned":job,"boot":boot})


def main(action):
    # An accidentally dispatched disabled checkout must stop before any transport.
    active, source = active_binding()
    w, t, primary, boot = scope(active, source)
    if action == "acquire":
        return acquire(active, source, w, t, primary, boot)
    root = w / "session-results"
    if action in ("latest","latest-after"):
        from installed_worker import latest
        return latest(root/("fresh-publication.json" if action=="latest" else "fresh-publication-after.json"),active["release"])
    if action=="selection":
        return write(root/"release23-selection.json",native_selection(root,active))
    if action=="results":
        import native_reader, score
        rel.publication_pair(root, active["release"])
        assert native_selection(root, active) == rel.read(root/"release23-selection.json")
        assert rel.canon(native_reader.affirm(root)) == rel.canon(rel.read(root/"native-replay.json"))
        ans = score.replay(root)
        assert rel.canon(ans) == rel.canon(rel.read(root/"independent-replay.json"))
        return write(root/"result.json",ans)
    raise ValueError(action)


if __name__=="__main__":
    assert len(sys.argv)==2
    main(sys.argv[1])
