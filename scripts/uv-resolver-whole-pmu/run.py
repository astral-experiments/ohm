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


def core_receipt(path):
    return [path.stat().st_size, sha(path)]


def install_roles(m, media, out):
    earlier = P["sdk_artifacts"]["both"]
    prior = media / earlier["name"]
    source = read(prior / "source.json")
    check(sha(prior / "source.json") == P["earlier_source_bytes_sha256"] and source["arm"] == "both" and
          source["source"]["rust"] == P["role_rust"]["earlier"] and source["source"]["tree"] == earlier["rust_tree"] and
          source["manifest"]["sources"]["cargo"]["revision"] == P["role_cargo"]["earlier"] and
          source["epoch"] == P["format_epochs"]["earlier"], "wrong earlier production source")
    save(out / "earlier-source.json", source)
    signed_tar, = (media / "signed").glob("*.tar.gz")
    final = P["final"]
    files = {"signed":signed_tar, "earlier":prior / "ohm.tar.gz", "rebased":media / "rebased" / (final["name"] + ".tar.gz")}
    pins = {"signed":P["signed"]["assets"][signed_tar.name]["digest"][7:], "earlier":earlier["inner_sha256"],
            "rebased":final["pkg_files"][files["rebased"].name]["sha256"]}
    summaries = {}
    for arm in P["arms"]:
        archive = files[arm]
        check(sha(archive) == pins[arm], f"{arm} distribution changed")
        sdk = m.WORK / ("sdk-" + arm)
        with tempfile.TemporaryDirectory(prefix="install-", dir=m.WORK) as tmp:
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="data")
            dist = Path(tmp) / ("rust-1.99.0-dev-" + P["target"])
            check(list(Path(tmp).iterdir()) == [dist], "unexpected distribution root")
            components = ["rustc", "cargo", "rust-std-" + P["target"]]
            subprocess.run([dist / "install.sh", "--prefix=" + str(sdk), "--disable-ldconfig",
                            "--components=" + ",".join(components)], check=True, timeout=360)
            inventories = {}
            for component in components:
                component_root = dist / component
                lines = (component_root / "manifest.in").read_text().splitlines()
                check(lines and all(line.startswith("file:") for line in lines), "unknown distribution manifest item")
                members = [line[5:] for line in lines]
                check(len(set(members)) == len(members) and
                      set(members) == {f.relative_to(component_root).as_posix() for f in component_root.rglob("*")
                                       if f.is_file() and f != component_root / "manifest.in"}, "incomplete distribution manifest")
                for name in members:
                    src, dst = component_root / name, sdk / name
                    check(name not in inventories and src.resolve().is_relative_to(component_root) and
                          dst.resolve().is_relative_to(sdk) and not src.is_symlink() and not dst.is_symlink(),
                          "duplicate or external component")
                    original = core_receipt(src)
                    check(core_receipt(dst) == original, (arm, "installer bytes", name))
                    inventories[name] = original
        check(all(inventories.get(k) == v for k, v in P["role_core"][arm].items()), f"{arm} component hashes differ from registered inputs")
        actual = {}
        for command in ("rustc", "cargo"):
            actual[command] = subprocess.check_output([sdk / "bin" / command, "-Vv"], text=True)
            revision = P["role_rust"][arm] if command == "rustc" else P["role_cargo"][arm]
            check("commit-hash: " + revision in actual[command] and "host: " + P["target"] in actual[command], "SDK banner")
        check(Path(subprocess.check_output([sdk / "bin/rustc", "--print", "sysroot"], text=True).strip()).resolve() == sdk, "wrong SDK sysroot")
        ldd = subprocess.check_output(["ldd", sdk / "bin/rustc"], text=True)
        loaded = {}
        for kind in ("librustc_driver", "libLLVM"):
            matches = [Path(p).resolve(strict=True) for n,p in re.findall(r"^\s*(\S+) => (\S+)", ldd, re.M) if n.startswith(kind)]
            check(len(matches) == 1 and matches[0].is_relative_to(sdk), f"wrong loaded {kind}")
            rel = matches[0].relative_to(sdk).as_posix()
            check(inventories[rel] == core_receipt(matches[0]), "loader picked different bytes")
            loaded[kind] = rel
        sections = subprocess.check_output(["readelf", "-SW", sdk / loaded["librustc_driver"]], text=True)
        check(".note.bolt_info" in sections, f"{arm} driver lacks BOLT section")
        summaries[arm] = {"labels":P["labels"][arm], "sdk":str(sdk), "rust":P["role_rust"][arm], "cargo":P["role_cargo"][arm],
                          "archive_sha256":pins[arm], "loaded":loaded, "banner":actual, "bolt":True}
        save(out / f"installed-{arm}-components.json", inventories)
    check(len({P["role_core"][arm]["lib/librustc_driver-b03bf00bec23bb9a.so"][1] for arm in P["arms"]}) == 3, "aliased compiler drivers")
    (m.WORK / "bin").mkdir()
    (m.WORK / "bin/cargo").symlink_to(m.WORK / "sdk-signed/bin/cargo")
    # The pinned qualifier uses this historical name solely for its unscored locked dependency fetch.
    (m.WORK / "sdk-base").symlink_to(m.WORK / "sdk-signed", target_is_directory=True)
    check(sha(m.WORK / "bin/cargo") == P["signed"]["cargo_sha256"] and
          (m.WORK / "sdk-base/bin/cargo").resolve() == (m.WORK / "bin/cargo").resolve(), "wrong common Cargo")
    save(out / "active-cargo.json", {"path":str((m.WORK / "bin/cargo").resolve()),
                                     "sha256":sha(m.WORK / "bin/cargo"), "source":P["measured_cargo"]})
    save(out / "installed-bridge.json", summaries)


def bridge_native_source(text):
    import hashlib
    check(hashlib.sha256(text.encode()).hexdigest() == P["native_source_sha256"], "native qualifier changed")
    old_arms = 'ARMS = ("base","nominal","both")'
    old_epoch = 'PINS["base_epoch"] if arm=="base" else PINS["epoch"]'
    check(text.count(old_arms) == text.count(old_epoch) == 1, "native role or epoch scope changed")
    return text.replace(old_arms, 'ARMS = ("signed","earlier","rebased")').replace(old_epoch, 'PINS["format_epochs"][arm]')


def stage_native(qualifier, folder):
    folder.mkdir()
    original = qualifier / "native-checks.py"
    program = folder / original.name
    program.write_text(bridge_native_source(original.read_text()))
    check(sha(program) == P["native_bridge_sha256"], "derived native qualifier changed")
    save(folder / "arms.json", {"format_epochs":P["format_epochs"]})
    probe = qualifier / "probe.rs"
    expect = [P["native_probe"]["bytes"], P["native_probe"]["sha256"]]
    check(core_receipt(probe) == expect, "original native probe changed")
    shutil.copyfile(probe, folder / probe.name)
    check(core_receipt(folder / probe.name) == expect, "relocated native probe changed")
    return program


def check_native(m, media, out):
    fixture = media / P["sdk_artifacts"]["both"]["name"] / "fixture"
    check({f.name:sha(f) for f in fixture.iterdir()} == P["fixture_sha256"], "trait fixture changed")
    folder = m.WORK / "native-qualifier"
    program = stage_native(m.HERE, folder)
    original = m.HERE / "native-checks.py"
    subprocess.run([sys.executable, "-IB", program, m.WORK, out, fixture], check=True, timeout=900)
    save(out / "native-source.json", {"base":sha(original), "bridge":sha(program), "fixtures":P["fixture_sha256"],
                                     "probe":core_receipt(folder / "probe.rs")})


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
    install_roles(m, media, out)
    check_native(m, media, out)
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
