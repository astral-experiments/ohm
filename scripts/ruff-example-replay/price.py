"""Measure whole ordinary Cargo histories with the two qualified physical Cargo programs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import factory
import study
from factory import need, save, sha

WORKFLOWS = {
    "examples": ["build", "-p", study.PACKAGE, "--examples"],
    "tests": ["test", "-p", study.PACKAGE, "--no-run"],
}


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", "repos/astral-experiments/ohm/" + path]))


def admit_worker(out, head, position):
    raw = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    need(str(uuid.UUID(raw)) == raw, "actual canonical Linux boot identity")
    evidence = {"head":head,"run":int(os.environ["GITHUB_RUN_ID"]),"position":position,
                "boot":raw,"runner":os.environ["RUNNER_NAME"],"host":platform.node(),
                "affinity":sorted(os.sched_getaffinity(0))}
    save(out / "admission.json", evidence)
    old = json.loads((HERE / "refused-original.json").read_bytes())
    name = f"Matched Cargo confirm-examples ({position})"
    for attempt in range(12):
        jobs = api(f"actions/runs/{evidence['run']}/jobs?per_page=100")["jobs"]
        current = [job for job in jobs if job["name"] == name]
        if len(current) == 1 and current[0]["runner_id"]:
            break
        if attempt < 11:
            time.sleep(2)
    need(len(current)==1, "authenticated active hosted matrix job")
    job = current[0]
    need(job["head_sha"]==head and job["run_id"]==evidence["run"] and job["run_attempt"]==1 and
         job["runner_name"]==evidence["runner"] and job["runner_id"]>0 and
         not any(job["runner_name"]==v["runner"] or job["runner_id"]==v["runner_id"]
                 for v in old["workers"]), "fresh machine assignment distinct from abandoned cohort")
    save(out / "authenticated-worker.json", job)
    return evidence


def enroll(root, ws, out, pilot):
    run = api("actions/runs/" + str(pilot["run"]))
    artifact = api("actions/artifacts/" + str(pilot["artifact"]))
    need(run["id"] == pilot["run"] and run["head_sha"] == pilot["head"] and
         run["head_branch"] == study.BRANCH.removeprefix("refs/heads/") and
         run["status"] == "completed" and run["conclusion"] == "success" and
         run["event"] == "workflow_dispatch" and run["run_attempt"] == 1, "completed physical gate")
    need(artifact["id"] == pilot["artifact"] and artifact["workflow_run"]["id"] == pilot["run"] and
         artifact["name"] == "ruff-example-replay-pilot" and not artifact["expired"] and
         artifact["digest"] == "sha256:" + pilot["zip_sha256"], "qualified original event archive")
    archive = root / "proof.zip"
    with archive.open("xb") as dest:
        subprocess.run(["gh", "api", "repos/astral-experiments/ohm/actions/artifacts/" +
                        str(pilot["artifact"]) + "/zip"], stdout=dest, check=True)
    need(sha(archive) == pilot["zip_sha256"], "raw original hardware artifact bytes")
    with ZipFile(archive) as z:
        original = json.loads(z.read("terminal.json"))
        source = json.loads(z.read("physical-source.json"))
        qualified = json.loads(z.read("qualified.json"))
    archive.unlink()
    need(original["sha"] == pilot["head"] and int(original["run"]) == pilot["run"] and
         original["binaries"] == pilot["binaries"] and
         source["registered"] == json.loads((HERE/"original-factory.json").read_bytes()) and
         qualified["parent"]["providers"] == qualified["candidate"]["providers"], "terminal physical gate")
    binaries = factory.recover_factory(root, ws, out)
    need(original["binaries"] == {arm:sha(file) for arm,file in binaries.items()} and
         original["sdk_rustc"] == sha(root/"distribution/bin/rustc") and
         original["sdk_wild"] == sha(root/"distribution"/study.WILD),
         "same physical Cargo, rustc, linker and standard library")
    save(out / "original.json", {"gate":pilot, "binary_receipt":original, "official_artifact":artifact})
    return binaries


def invoke(clock, args, out, phase, env, src):
    cmd = ["cargo", "+ohm", *args, "--locked", "--offline", "-j4", "--message-format=json"]
    actual = [clock, out / (phase + "-clock.json"), *cmd]
    result = subprocess.run(actual, cwd=src, env=env, capture_output=True, timeout=1800)
    # Keep bytes in memory. The next Cargo invocation starts before reading the target,
    # fingerprints, executables or the counter's saved data.
    if result.returncode:
        study.compressed(out / (phase + "-failed-stdout.gz"), result.stdout)
        study.compressed(out / (phase + "-failed-stderr.gz"), result.stderr)
    need(result.returncode == 0, (phase, result.returncode, result.stderr[-1500:]))
    return result, cmd


def receipt(result, cmd, out, phase, root):
    study.compressed(out / (phase + "-stdout.gz"), result.stdout)
    study.compressed(out / (phase + "-stderr.gz"), result.stderr)
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    need(rows and rows[-1] == {"reason":"build-finished","success":True}, "terminal ordinary Cargo")
    count = json.loads((out / (phase + "-clock.json")).read_bytes())
    need(count["code"] == count["event_errno"] == 0 and count["enabled"] == count["running"] > 0
         and count["instructions"] > 0, "uncensored inherited user-mode instructions")
    products = []
    images = {}
    for row in rows:
        if row.get("reason") != "compiler-artifact":
            continue
        kind, name = row["target"]["kind"], row["target"]["name"]
        products.append([row["package_id"],kind,name,row["profile"]["test"],row["fresh"]])
        if row.get("executable"):
            file = Path(row["executable"]).resolve(strict=True)
            need(file.is_relative_to(root / "slot"), "private output")
            images["/".join([*kind,name,str(row["profile"]["test"])])] = str(file)
    return {"instructions":count["instructions"],"products":sorted(products),"images":images,"argv":cmd}


def behaviors(images, src, env, names, workflow):
    results = {}
    for tag, path in sorted(images.items()):
        kind, name, test = tag.split("/")
        file = Path(path)
        if kind != "example" and test != "True":
            continue
        need(file.is_file() and not file.is_symlink(), "physical product")
        with file.open("rb") as stream:
            need(stream.read(7) == b"\x7fELF\x02\x01\x01", "GNU native executable")
        args = [file, "--list", "--format", "terse"] if test == "True" else [file]
        run = subprocess.run(args, cwd=src, env=env, capture_output=True, timeout=180, check=True)
        if kind == "example":
            need(name in names, "real Ruff example")
        if test == "True":
            need(not run.stderr and (b": test" in run.stdout or b"0 tests" in run.stdout or not run.stdout.strip()),
                 ("runnable test harness", name, run.stdout[-1500:]))
        results[tag] = [sha(file), file.stat().st_size, hashlib.sha256(run.stdout).hexdigest(),
                        hashlib.sha256(run.stderr).hexdigest()]
    root_examples = {tag.split("/")[1] for tag in results if tag.startswith("example/")}
    if workflow == "examples":
        need(root_examples == names, "exact twelve examples")
    else:
        need(any(tag.startswith("test/ruff/") for tag in results), "real renderer integration test")
    return results


def history(root, src, env, out, w, seed, binaries, clock, arm, workflow, inspect):
    study.select(root, binaries, arm)
    study.reset(env, seed, w)
    patch = Path(w.__file__).parent / "renderer.patch"
    w.git(src, "apply", "--reverse", patch)
    w.sources(src, "old")
    out.mkdir()
    args = WORKFLOWS[workflow]
    raw = {"cold":invoke(clock, args, out, "cold", env, src)}
    cold = receipt(*raw["cold"], out, "cold", root)
    old_images = behaviors(cold["images"], src, env, w.NAMES, workflow)
    old_storage = study.footprint(env)
    w.git(src, "apply", patch)
    w.sources(src, "corrected")
    for phase in ("edit", "first-unchanged", "settled"):
        raw[phase] = invoke(clock, args, out, phase, env, src)
    records = {"cold":cold, **{phase:receipt(*raw[phase], out, phase, root)
                              for phase in ("edit", "first-unchanged", "settled")}}
    changed = records["first-unchanged"]
    roster = [item[:4] for item in changed["products"]]
    need(all([item[:4] for item in row["products"]] == roster for row in records.values()),
         "complete Cargo unit roster across the real edit")
    images = behaviors(changed["images"], src, env, w.NAMES, workflow)
    storage = study.footprint(env)
    if inspect:
        traced = study.execute(root, src, env, out / "traced-settled", args, trace=True)
        owners = {}
        for row in traced["execs"]:
            opts = row["args"]
            if row["kind"] == "rustc" and "--crate-name" in opts:
                crate = opts[opts.index("--crate-name") + 1]
                if crate in w.NAMES:
                    owners[crate] = {"relink": "link-only" in opts and any(s.endswith(".rlink") for s in opts)}
        linked = [Path(row["args"][row["args"].index("-o")+1]).name for row in traced["execs"]
                  if row["kind"] == "wild" and "-o" in row["args"]]
        if workflow == "examples":
            need(set(owners) == w.NAMES and all(linked.count(name) == 1 for name in w.NAMES) and
                 all(v["relink"] == (arm == "candidate") for v in owners.values()), "same twelve genuine links")
        save(out / "physical-owners.json", {"owners":owners, "linked":linked})
    return {"arm":arm,"workflow":workflow,"phases":records,"old_images":old_images,"new_images":images,
            "cold_storage":old_storage,"new_storage":storage}


def main():
    ws = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    head = os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm" and os.environ["GITHUB_REF"] == study.BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["REVIEWED_HEAD"] == head,
         "reviewed nonrelease price worker")
    for folder, registered in (("enrolled",head),("historical",study.RENDERER)):
        need(subprocess.check_output(["git","-C",ws / folder,"rev-parse","HEAD"]).decode().strip()==registered,
             "physical QA checkout")
    sys.path.insert(0, str(ws / "historical/scripts/gnu-example-ceiling"))
    import workload as w
    import pmu

    position = int(os.environ["POSITION"])
    need(1 <= position <= 6, "one of six independent pairs")
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "ruff-example-price"
    root.mkdir()
    need(shutil.disk_usage(root).free > 6 * 2**30, "private hosted comparison storage")
    out = root / "evidence"
    out.mkdir()
    scope = os.environ["PRICE_SCOPE"]
    need(scope in ("price", "confirm-examples"), "registered comparison scope")
    if scope == "confirm-examples":
        admit_worker(out, head, position)
    binaries = enroll(root, ws, out, json.loads((HERE / "official-pilot.json").read_bytes()))
    cpus = sorted(os.sched_getaffinity(0))
    need(len(cpus) >= 4, "four available paired CPUs")
    os.sched_setaffinity(0, cpus[:4])
    bins = pmu.compilers(root)
    pmu.calibration(bins, out)
    study.select(root, binaries, "parent")
    src = w.source(root)
    env = w.env_for(root)
    seed = w.prepare_registry(root, src, env, out)
    arm_order = ["parent","candidate"] if position % 2 else ["candidate","parent"]
    actions = ["examples","tests"] if position in (1,4,5) else ["tests","examples"]
    if scope == "confirm-examples":
        actions = ["examples"]
    all_results = []
    for workflow in actions:
        by_arm = {}
        for repeat, order in enumerate((arm_order, arm_order[::-1])):
            for arm in order:
                label = workflow + "-" + str(repeat) + "-" + arm
                result = history(root, src, env, out / label, w, seed, binaries, bins/"plain",
                                 arm, workflow, inspect=repeat==0)
                save(out / (label + ".json"), result)
                by_arm.setdefault(arm, []).append(result)
                all_results.append(result)
        # Independent empty NEW target. Validate both arm histories and every linked output.
        study.select(root, binaries, "parent")
        study.reset(env, seed, w)
        clean = study.execute(root, src, env, out / (workflow+"-independent-new"), WORKFLOWS[workflow])
        images = behaviors({k:v[0] for k,v in clean["executables"].items()},src,env,w.NAMES,workflow)
        need(all(item["new_images"] == images for items in by_arm.values() for item in items) and
             len({json.dumps(item["old_images"],sort_keys=True) for items in by_arm.values() for item in items})==1,
             ("independent clean full bytes and behavior", workflow))
    save(out / "terminal.json", {"schema":2,"scope":scope,"head":head,"run":os.environ["GITHUB_RUN_ID"],
         "job":os.environ["GITHUB_JOB"],"position":position,"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "runner":os.environ["RUNNER_NAME"],"cpus":cpus[:4],"platform":platform.platform(),
         "ordering":arm_order,"workflows":actions,"signed":sha(root/"distribution/bin/rustc"),
         "wild":sha(root/"distribution"/study.WILD),"cargo":{a:sha(p) for a,p in binaries.items()},
         "phases":[[r["workflow"],r["arm"],{ph:data["instructions"] for ph,data in r["phases"].items()}]
                   for r in all_results]})


if __name__ == "__main__":
    main()
