"""Reproduce the qualified resolver first edit in separately instrumented and native visits."""
import importlib.util
import itertools
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intake import HERE, P, check, hosted_roots, read, save, scope, sha


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def orders():
    holds = []
    for seed in P["holds"]:
        rng = random.Random(seed)
        groups = list(itertools.permutations(P["arms"]))
        rng.shuffle(groups)
        mode_orders = [P["modes"], P["modes"][::-1]] * 3
        rng.shuffle(mode_orders)
        holds.append([{"arms": list(group), "modes": mode} for group, mode in zip(groups, mode_orders, strict=True)])
    return holds


def cpu_receipt(out):
    allowed = sorted(os.sched_getaffinity(0))
    cores = {}
    for cpu in allowed:
        t = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        pair = tuple((t / key).read_text().strip() for key in ("physical_package_id", "core_id"))
        cores.setdefault(pair, cpu)
    check(len(cores) >= 8, "fewer than eight separate physical cores")
    chosen = sorted(list(cores.values())[:8])
    os.sched_setaffinity(0, chosen)
    return {"cpus": chosen, "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "runner": os.environ["RUNNER_NAME"], "cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
            "machine": platform.machine()}


def verified_checkouts(w):
    for name, revision in (("qualified", P["qualifier"]), ("pilot", P["pilot"]),
                           ("calibrator", P["calibrator"]), ("observers", P["observer"])):
        repo = w / name
        check(subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip() == revision and
              not subprocess.check_output(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"]),
              f"source checkout changed: {name}")
    directory = w / "pilot/scripts/branch-return-pmu"
    for name, expected in (("meter.py", "5884db65be186a23811bfbf7743a46c25679c995"),
                           ("bindings.py", "8345df71c46383086cc82745b6091c07b5598271")):
        check(subprocess.check_output(["git", "hash-object", directory / name], text=True).strip() == expected, name)
    path = w / "pilot/scripts/ctfe-crossover-pilot/pilot.py"
    check("branch-return-pmu/meter.py" in path.read_text(), "counter route differs from the original pilot")


def meter_root(tmp):
    return tmp / "ohm-branch-object-qa/logs"


def calibrate():
    scope()
    w, out, tmp = hosted_roots()
    verified_checkouts(w)
    check(platform.system() == "Linux" and platform.machine() == "x86_64", "unexpected architecture")
    out.mkdir(exist_ok=True)
    save(out / "host.json", cpu_receipt(out))
    dest = meter_root(tmp)
    dest.mkdir(parents=True)
    meter = w / "pilot/scripts/branch-return-pmu/meter.py"
    subprocess.run([sys.executable, "-IB", meter, w / "calibrator", w / "observers"], check=True, timeout=480)
    ready = read(dest / "meter-ready.json")
    host = read(out / "host.json")
    check(ready["boot"] == host["boot"] and ready["affinity"] == host["cpus"] and
          ready["calibrator"] == P["calibrator"] and ready["observer"] == P["observer"] and
          Path(ready["plain"]) == dest / "observers/plain", "wrong boot, counter or mask")
    clocks = sorted((dest / "calibration").glob("whole-*-*.json"))
    check(len(clocks) == 28, "missing original fork, exec and thread calibration clocks")
    for path in clocks:
        row = read(path)
        check(row["event_errno"] == row["code"] == 0 and row["instructions"] > 0 and
              row["running"] == row["enabled"] > 0, "missing or multiplexed calibration counter")
    shutil.copytree(dest, out / "pmu-calibration")
    save(out / "calibration.json", {"ready": ready, "plain_sha256": sha(Path(ready["plain"])),
         "unmultiplexed_calibration_clocks": len(clocks), "abi": read(dest / "observer.json")["abi"]})


def signed_install(m, media):
    cfg = P["signed"]
    with tempfile.TemporaryDirectory(prefix="signed-install-", dir=m.WORK) as tmp:
        archive, = (media / "signed").glob("*.tar.gz")
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="data")
        dist = Path(tmp) / ("rust-1.99.0-dev-" + P["target"])
        install = m.WORK / "sdk-signed"
        subprocess.run([dist / "install.sh", "--prefix=" + str(install), "--disable-ldconfig",
                        "--components=rustc,cargo,rust-std-" + P["target"]], check=True, timeout=360)
    driver, = (install / "lib").glob("librustc_driver-*.so")
    for f, key in ((driver, "driver_sha256"), (install / "bin/rustc", "launcher_sha256"),
                   (install / "bin/cargo", "cargo_sha256")):
        check(sha(f) == cfg[key], f)
    for tool, key in (("rustc", "rust"), ("cargo", "cargo")):
        banner = subprocess.check_output([install / "bin" / tool, "-Vv"], text=True)
        check("commit-hash: " + cfg[key] in banner and "host: " + P["target"] in banner, banner)
    cargo = m.WORK / "bin/cargo"
    check(cargo.is_symlink() and cargo.resolve() == m.WORK / "sdk-base/bin/cargo", "unexpected original Cargo path")
    cargo.unlink()
    cargo.symlink_to(install / "bin/cargo")
    return install


def cpu_data(mask):
    wanted = {f"cpu{i}" for i in mask}
    return [line for line in Path("/proc/stat").read_text().splitlines() if line.split()[0] in wanted]


def first_pmu(m, meter, plain, log, mask):
    cwd = m.UV
    argv = [str(m.WORK / "bin/cargo"), *P["argv"]]
    clock = log / "whole-clock.json"
    before = cpu_data(mask)
    start = time.monotonic_ns()
    proc = subprocess.run([plain, clock, *argv], cwd=cwd, env=m.environment(), capture_output=True, timeout=240)
    stop = time.monotonic_ns()
    (log / "first-edit.stdout").write_bytes(proc.stdout)
    (log / "first-edit.stderr").write_bytes(proc.stderr)
    row = {"argv": argv, "observer_argv": [str(plain), str(clock), *argv], "exit": proc.returncode,
           "start_ns": start, "end_ns": stop, "ns": stop - start, "cpus": mask, "cpu_before": before,
           "cpu_after": cpu_data(mask), "dirty": dirty(proc.stderr)}
    save(log / "first-edit.json", row)
    check(proc.returncode == 0, ("Cargo or the PMU failed", proc.returncode, proc.stderr[-1000:]))
    counter = meter.clock(clock, 0)
    check(counter["running"] == counter["enabled"], "multiplexed counter, reject this experiment")
    return row


def dirty(stderr):
    return sorted(n.decode() for n in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v", stderr, re.M))


def trial(m, case, delta, arm, key, mode, mask, out, meter, plain, native_command):
    physical = m.WORK / ("sdk-" + arm)
    check(not m.SLOT.exists() and shutil.disk_usage(m.WORK).free > 20 << 30, "target was not empty or disk floor")
    check(sha(m.WORK / "bin/cargo") == P["signed"]["cargo_sha256"], "wrong common Cargo")
    def invoke(log, phase, cpu_mask, edit):
        check(m.SDK.resolve(strict=True) == physical and sorted(os.sched_getaffinity(0)) == mask,
              "different selected SDK or CPU set")
        if mode == "pmu" and phase == "first-edit":
            row = first_pmu(m, meter, plain, log, mask)
        else:
            row = native_command(log, phase, cpu_mask, edit)
        if phase != "cold":
            expect = P["expected_first_dirty"] if phase == "first-edit" else P["expected_unchanged_dirty"]
            check(row["dirty"] == expect, (key, arm, phase, row["dirty"], expect))
        return row
    m.command = invoke
    rows = m.trial(case, delta, arm, key, mask, out)
    check(list(rows) == ["cold", "unchanged-parent", "first-edit", "unchanged-child"] and not m.SLOT.exists(),
          "first-edit history was incomplete")


def uv_witness(m, case, delta, out):
    basic = "workspace::tests::exclude_package"
    child = basic + "_with_normalized_glob_and_escaped_root"
    for arm in P["arms"]:
        m.switch(arm)
        with tempfile.TemporaryDirectory(prefix="uv-exclude-", dir=m.WORK) as tmp:
            tmp = Path(tmp)
            for name in ("home", "tmp"):
                (tmp / name).mkdir()
            env = m.environment() | {"HOME": str(tmp / "home"), "TMPDIR": str(tmp / "tmp"),
                  "CARGO_HOME": str(m.DEPS), "CARGO_TARGET_DIR": str(tmp / "target"), "CARGO_INCREMENTAL": "0",
                  "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_PROFILE_DEV_DEBUG": "0", "INSTA_UPDATE": "no"}
            m.git("reset", "--hard", "--quiet", case["parent"])
            for role, expected in (("A", [basic]), ("B", sorted((basic, child)))):
                if role == "B":
                    m.git("apply", "--index", "-", data=delta)
                    check(m.git("write-tree") == m.git("rev-parse", case["child"] + "^{tree}"), "wrong witness edit")
                argv = [m.WORK / "bin/cargo", "test", "--offline", "--locked", "-j4", "-p", "uv-workspace",
                        "--lib", basic, "--", "--test-threads=1"]
                p = subprocess.run(argv, cwd=m.UV, env=env, capture_output=True, timeout=1500)
                path = out / f"uv-exclusion-{arm}-{role}"
                path.with_suffix(".stdout").write_bytes(p.stdout)
                path.with_suffix(".stderr").write_bytes(p.stderr)
                names = sorted(x.decode() for x in re.findall(rb"^test (\S+) \.\.\. ok$", p.stdout, re.M))
                check(p.returncode == 0 and names == expected, (arm, role, p.returncode, names))
                save(path.with_suffix(".json"), {"passed": names, "argv": list(map(str, argv))})
    m.git("reset", "--hard", "--quiet", case["parent"])


def run():
    scope()
    w, out, tmp = hosted_roots()
    verified_checkouts(w)
    host = cpu_receipt(out)
    check(read(out / "host.json") == host, "different boot or physical affinity since calibration")
    cert = read(out / "calibration.json")
    plain = Path(cert["ready"]["plain"])
    check(sha(plain) == cert["plain_sha256"], "PMU observer changed")
    m = load(w / "qualified/scripts/rc23-trait-qualification/measure.py", "uv_qualification")
    meter = load(w / "pilot/scripts/branch-return-pmu/meter.py", "ohm_pmu")
    check(P["argv"] == m.P["command"] and m.P["jobs"] == 8 and m.P["cases"][0] == P["case"], "endpoint or uv edit changed")
    check(m.EVIDENCE == out and m.WORK == tmp / "rc23-trait-work", "unexpected frozen harness layout")
    m.WORK.mkdir()
    media = w / "sdk-media"
    m.install()
    shipped = signed_install(m, media)
    installed = read(out / "installed.json")
    for name, pin in P["sdk_artifacts"].items():
        row = installed[name]
        check(row["source"]["source"]["rust"] == pin["source_commit"] and
              row["source"]["source"]["tree"] == pin["rust_tree"] and row["archive_sha256"] == pin["inner_sha256"] and
              row["rustc_sha256"] == pin["launcher_sha256"] and row["cargo_sha256"] == pin["cargo_sha256"] and
              row["libraries"]["librustc_driver"] == pin["driver_sha256"], "installed optimized SDK mismatch")
    save(out / "active-cargo.json", {"path": str((m.WORK / "bin/cargo").resolve()), "sha256": sha(shipped / "bin/cargo"),
                                     "source": P["measured_cargo"]})
    native_checks = m.HERE / "native-checks.py"
    subprocess.run([sys.executable, "-IB", native_checks, m.WORK, out, media / "rc23-trait-sdk-both/fixture"],
                   check=True, timeout=900)
    case = P["case"]
    delta = m.fetch(case)
    save(out / "protocol.json", P)
    save(out / "orders.json", orders())
    trials = out / "trials"
    trials.mkdir()
    native = m.command
    for arm in P["arms"]:
        trial(m, case, delta, arm, "excluded-pmu", "pmu", host["cpus"], trials, meter, plain, native)
    for h, hold in enumerate(orders(), 1):
        for n, group in enumerate(hold, 1):
            for mode in group["modes"]:
                for arm in group["arms"]:
                    key = f"h{h}-{n:02}-{mode}"
                    trial(m, case, delta, arm, key, mode, host["cpus"], trials, meter, plain, native)
            print(f"hold {h} set {n} completed", flush=True)
    m.command = native
    uv_witness(m, case, delta, out)
    shutil.copyfile(HERE / "read.py", out / "read.py")
    subprocess.run([sys.executable, "-IB", HERE / "read.py", out], check=True)


if __name__ == "__main__":
    {"calibrate": calibrate, "run": run}[sys.argv[1]]()
